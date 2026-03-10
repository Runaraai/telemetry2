package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"regexp"
	"strings"
	"syscall"
	"time"

	"github.com/gofrs/flock"
	"go.uber.org/zap"
	"gopkg.in/yaml.v3"
)

const (
	AgentVersion    = "2.0.8"
	DefaultAPIBaseURL = "https://omniference.com"
	ConfigFile        = "/etc/omniference/config.env"
	DeploymentRoot    = "/var/lib/omniference/deployments"
	StateFile         = "/var/lib/omniference/agent-state.json"
	LockFile          = "/var/lock/omniference-agent.lock"
)

// Custom error types for better error handling
var (
	ErrConfigNotFound   = errors.New("config file not found")
	ErrInvalidConfig    = errors.New("invalid configuration")
	ErrDeploymentFailed = errors.New("deployment failed")
	ErrDockerNotReady   = errors.New("docker not ready")
	ErrGPUNotDetected   = errors.New("GPU not detected")
	ErrInvalidInstanceID = errors.New("invalid instance ID format")
)

// Global HTTP client with proper timeouts and connection pooling
var httpClient = &http.Client{
	Timeout: 30 * time.Second,
	Transport: &http.Transport{
		MaxIdleConns:          100,
		IdleConnTimeout:       90 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ResponseHeaderTimeout: 30 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
	},
}

// instanceIDRegex validates instance ID format (alphanumeric, dash, underscore only)
var instanceIDRegex = regexp.MustCompile(`^[a-zA-Z0-9_-]{1,64}$`)

type Config struct {
	APIKey     string
	InstanceID string
	APIBaseURL string
}

type DeploymentConfig struct {
	InstanceID         string `json:"instance_id"`
	RunID              string `json:"run_id"`
	DockerCompose      string `json:"docker_compose"`
	PrometheusConfig   string `json:"prometheus_config"`
	BackendURL         string `json:"backend_url"`
	PollInterval       int    `json:"poll_interval"`
	EnableProfiling    bool   `json:"enable_profiling"`
	DCGMCollectors     string `json:"dcgm_collectors_csv"`
	NvidiaSMIExporter  string `json:"nvidia_smi_exporter"`
	DCGMHealthExporter string `json:"dcgm_health_exporter"`
	TokenExporter      string `json:"token_exporter"`
}

type HeartbeatRequest struct {
	InstanceID   string                 `json:"instance_id"`
	APIKey       string                 `json:"api_key"`
	AgentVersion string                 `json:"agent_version"`
	Phase        string                 `json:"phase"`
	Status       string                 `json:"status"`
	Message      string                 `json:"message,omitempty"`
	Metadata     map[string]interface{} `json:"metadata,omitempty"`
}

// AgentState tracks persistent state for recovery
type AgentState struct {
	Phase         string    `json:"phase"`
	Status        string    `json:"status"`
	LastHeartbeat time.Time `json:"last_heartbeat"`
	DeploymentDir string    `json:"deployment_dir"`
	Version       string    `json:"version"`
}

type ProvisioningAgent struct {
	Config           *Config
	DeploymentConfig *DeploymentConfig
	Logger           *zap.Logger
	ctx              context.Context
	cancel           context.CancelFunc
}

// LoadConfig reads configuration from environment variables first, then falls back to config file
func LoadConfig() (*Config, error) {
	config := &Config{
		APIBaseURL: DefaultAPIBaseURL,
	}

	// Read from environment first (production - secrets should be in env vars)
	config.APIKey = os.Getenv("OMNIFERENCE_API_KEY")
	config.InstanceID = os.Getenv("OMNIFERENCE_INSTANCE_ID")
	if apiURL := os.Getenv("OMNIFERENCE_API_URL"); apiURL != "" {
		config.APIBaseURL = apiURL
	}

	// Fallback to config file for development only
	if config.APIKey == "" || config.InstanceID == "" {
		if data, err := os.ReadFile(ConfigFile); err == nil {
			lines := strings.Split(string(data), "\n")
			for _, line := range lines {
				line = strings.TrimSpace(line)
				if line == "" || strings.HasPrefix(line, "#") {
					continue
				}
				parts := strings.SplitN(line, "=", 2)
				if len(parts) != 2 {
					continue
				}
				key, value := strings.TrimSpace(parts[0]), strings.TrimSpace(parts[1])
				switch key {
				case "API_KEY":
					if config.APIKey == "" {
						config.APIKey = value
					}
				case "INSTANCE_ID":
					if config.InstanceID == "" {
						config.InstanceID = value
					}
				case "API_BASE_URL":
					if config.APIBaseURL == DefaultAPIBaseURL {
						config.APIBaseURL = value
					}
				}
			}
		}
	}

	if config.APIKey == "" {
		return nil, fmt.Errorf("%w: OMNIFERENCE_API_KEY environment variable or API_KEY in %s must be set", ErrInvalidConfig, ConfigFile)
	}
	if config.InstanceID == "" {
		return nil, fmt.Errorf("%w: OMNIFERENCE_INSTANCE_ID environment variable or INSTANCE_ID in %s must be set", ErrInvalidConfig, ConfigFile)
	}

	return config, nil
}

// NewProvisioningAgent creates a new agent instance with validated configuration
func NewProvisioningAgent(ctx context.Context) (*ProvisioningAgent, error) {
	config, err := LoadConfig()
	if err != nil {
		return nil, err
	}

	// Validate instance ID format (alphanumeric, dash, underscore only)
	if !instanceIDRegex.MatchString(config.InstanceID) {
		return nil, fmt.Errorf("%w: must be alphanumeric with dash/underscore, max 64 chars", ErrInvalidInstanceID)
	}

	// Initialize structured logger
	logger, err := zap.NewProduction()
	if err != nil {
		return nil, fmt.Errorf("failed to initialize logger: %w", err)
	}

	agentCtx, cancel := context.WithCancel(ctx)

	return &ProvisioningAgent{
		Config: config,
		Logger: logger,
		ctx:    agentCtx,
		cancel: cancel,
	}, nil
}

// getDeploymentDir returns the deployment directory path for this instance
func (a *ProvisioningAgent) getDeploymentDir() string {
	return filepath.Join(DeploymentRoot, a.Config.InstanceID)
}

// makeRequest performs an HTTP POST request with proper context and error handling
func (a *ProvisioningAgent) makeRequest(ctx context.Context, url string, payload interface{}) (*http.Response, error) {
	jsonData, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal request: %w", err)
	}

	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewBuffer(jsonData))
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("request failed: %w", err)
	}

	return resp, nil
}

// retryableRequest performs a request with exponential backoff retry logic
func (a *ProvisioningAgent) retryableRequest(ctx context.Context, url string, payload interface{}, maxRetries int) (*http.Response, error) {
	var lastErr error

	for attempt := 0; attempt < maxRetries; attempt++ {
		resp, err := a.makeRequest(ctx, url, payload)
		if err == nil {
			return resp, nil
		}

		lastErr = err

		// Don't retry on non-retryable errors
		if !isRetryable(err) {
			return nil, err
		}

		// Exponential backoff
		if attempt < maxRetries-1 {
			backoff := time.Duration(1<<uint(attempt)) * time.Second
			a.Logger.Warn("Request failed, retrying",
				zap.Int("attempt", attempt+1),
				zap.Int("max_retries", maxRetries),
				zap.Duration("backoff", backoff),
				zap.Error(err),
			)

			select {
			case <-time.After(backoff):
			case <-ctx.Done():
				return nil, ctx.Err()
			}
		}
	}

	return nil, fmt.Errorf("max retries exceeded: %w", lastErr)
}

// isRetryable determines if an error should trigger a retry
func isRetryable(err error) bool {
	if err == nil {
		return false
	}

	// Network errors are retryable
	if errors.Is(err, syscall.ECONNREFUSED) ||
		errors.Is(err, syscall.ETIMEDOUT) ||
		errors.Is(err, syscall.ECONNRESET) {
		return true
	}

	// HTTP 5xx errors are retryable
	errStr := err.Error()
	return strings.Contains(errStr, "status 5") ||
		strings.Contains(errStr, "network") ||
		strings.Contains(errStr, "timeout") ||
		strings.Contains(errStr, "connection refused")
}

// FetchDeploymentConfig retrieves deployment configuration from the backend
func (a *ProvisioningAgent) FetchDeploymentConfig(pollInterval int, enableProfiling bool) error {
	url := fmt.Sprintf("%s/api/telemetry/provision/config", a.Config.APIBaseURL)

	metadata := a.collectMetadata()
	metadata["agent_version"] = AgentVersion

	payload := map[string]interface{}{
		"instance_id":      a.Config.InstanceID,
		"api_key":          a.Config.APIKey,
		"poll_interval":    pollInterval,
		"enable_profiling": enableProfiling,
		"metadata":         metadata,
	}

	resp, err := a.retryableRequest(a.ctx, url, payload, 3)
	if err != nil {
		return fmt.Errorf("failed to fetch config: %w", err)
	}
	defer func() {
		io.Copy(io.Discard, resp.Body) // Drain body for connection reuse
		resp.Body.Close()
	}()

	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024*1024)) // Max 1MB
		return fmt.Errorf("failed to fetch config: status %d, body: %s", resp.StatusCode, string(body))
	}

	var configResp DeploymentConfig
	if err := json.NewDecoder(resp.Body).Decode(&configResp); err != nil {
		return fmt.Errorf("failed to decode config: %w", err)
	}

	a.DeploymentConfig = &configResp
	return nil
}

// ValidateDeploymentConfig validates the deployment configuration
func (a *ProvisioningAgent) ValidateDeploymentConfig() error {
	if a.DeploymentConfig == nil {
		return errors.New("deployment config is nil")
	}

	// Validate instance ID matches
	if a.DeploymentConfig.InstanceID != a.Config.InstanceID {
		return fmt.Errorf("instance ID mismatch: expected %s, got %s",
			a.Config.InstanceID, a.DeploymentConfig.InstanceID)
	}

	// Validate docker-compose content
	if len(a.DeploymentConfig.DockerCompose) == 0 {
		return errors.New("docker-compose content is empty")
	}
	if len(a.DeploymentConfig.DockerCompose) > 1024*1024 { // 1MB max
		return errors.New("docker-compose content exceeds 1MB")
	}

	// Validate it's valid YAML
	var compose map[string]interface{}
	if err := yaml.Unmarshal([]byte(a.DeploymentConfig.DockerCompose), &compose); err != nil {
		return fmt.Errorf("invalid docker-compose YAML: %w", err)
	}

	// Validate prometheus config
	if len(a.DeploymentConfig.PrometheusConfig) == 0 {
		return errors.New("prometheus config is empty")
	}

	var prometheus map[string]interface{}
	if err := yaml.Unmarshal([]byte(a.DeploymentConfig.PrometheusConfig), &prometheus); err != nil {
		return fmt.Errorf("invalid prometheus config YAML: %w", err)
	}

	return nil
}

func (a *ProvisioningAgent) collectMetadata() map[string]interface{} {
	metadata := map[string]interface{}{}

	if count, err := a.detectGPUCount(); err == nil && count > 0 {
		metadata["gpu_count"] = count
	}

	// Detect DCGM version for exporter image selection
	if dcgmImage, err := a.detectDCGMImage(); err == nil && dcgmImage != "" {
		metadata["dcgm_image"] = dcgmImage
	}

	return metadata
}

// detectDCGMImage detects installed DCGM version and returns compatible exporter image
func (a *ProvisioningAgent) detectDCGMImage() (string, error) {
	// Method 1: Check for libdcgm.so in common locations using Go native file operations
	libPaths := []string{
		"/usr/lib/x86_64-linux-gnu",
		"/usr/local/dcgm/lib64",
		"/usr/lib64",
	}

	for _, dir := range libPaths {
		entries, err := os.ReadDir(dir)
		if err != nil {
			continue
		}
		for _, entry := range entries {
			name := entry.Name()
			if strings.HasPrefix(name, "libdcgm.so.") {
				if strings.Contains(name, "libdcgm.so.4") {
					return "nvcr.io/nvidia/k8s/dcgm-exporter:4.2.0-4.1.0-ubuntu22.04", nil
				} else if strings.Contains(name, "libdcgm.so.3") {
					return "nvcr.io/nvidia/k8s/dcgm-exporter:3.1.8-3.1.5-ubuntu20.04", nil
				}
			}
		}
	}

	// Method 2: Check if dcgmi command exists and works (no shell)
	cmd := exec.CommandContext(a.ctx, "dcgmi", "--version")
	output, err := cmd.Output()
	if err == nil && len(output) > 0 {
		outputStr := strings.ToLower(string(output))
		if strings.Contains(outputStr, "4.") || strings.Contains(outputStr, "version 4") {
			return "nvcr.io/nvidia/k8s/dcgm-exporter:4.2.0-4.1.0-ubuntu22.04", nil
		}
		return "nvcr.io/nvidia/k8s/dcgm-exporter:3.1.8-3.1.5-ubuntu20.04", nil
	}

	// Method 3: Check if datacenter-gpu-manager package is installed (no shell)
	cmd = exec.CommandContext(a.ctx, "dpkg", "-l", "datacenter-gpu-manager")
	if err := cmd.Run(); err == nil {
		return "nvcr.io/nvidia/k8s/dcgm-exporter:3.1.8-3.1.5-ubuntu20.04", nil
	}

	// Method 4: Check if DCGM service is running (no shell)
	cmd = exec.CommandContext(a.ctx, "systemctl", "is-active", "--quiet", "dcgm")
	if err := cmd.Run(); err == nil {
		return "nvcr.io/nvidia/k8s/dcgm-exporter:3.1.8-3.1.5-ubuntu20.04", nil
	}

	return "", nil
}

func (a *ProvisioningAgent) detectGPUCount() (int, error) {
	cmd := exec.CommandContext(a.ctx, "nvidia-smi", "--list-gpus")
	output, err := cmd.Output()
	if err != nil {
		return 0, fmt.Errorf("%w: %v", ErrGPUNotDetected, err)
	}

	lines := strings.Split(strings.TrimSpace(string(output)), "\n")
	count := 0
	for _, line := range lines {
		if strings.TrimSpace(line) != "" {
			count++
		}
	}

	return count, nil
}

// SendHeartbeat sends a heartbeat to the backend
func (a *ProvisioningAgent) SendHeartbeat(phase, status, message string, metadata map[string]interface{}) error {
	merged := map[string]interface{}{}
	for k, v := range metadata {
		merged[k] = v
	}
	// Include run_id in heartbeats so the UI can detect run_id mismatches.
	// Do NOT include ingest tokens or other secrets.
	if a.DeploymentConfig != nil && a.DeploymentConfig.RunID != "" {
		merged["run_id"] = a.DeploymentConfig.RunID
	}

	req := HeartbeatRequest{
		InstanceID:   a.Config.InstanceID,
		APIKey:       a.Config.APIKey,
		AgentVersion: AgentVersion,
		Phase:        phase,
		Status:       status,
		Message:      message,
		Metadata:     merged,
	}

	url := fmt.Sprintf("%s/api/telemetry/provision/callbacks", a.Config.APIBaseURL)
	resp, err := a.retryableRequest(a.ctx, url, req, 3)
	if err != nil {
		return fmt.Errorf("failed to send heartbeat: %w", err)
	}
	defer func() {
		io.Copy(io.Discard, resp.Body)
		resp.Body.Close()
	}()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		body, _ := io.ReadAll(io.LimitReader(resp.Body, 1024*1024))
		return fmt.Errorf("heartbeat failed: status %d, body: %s", resp.StatusCode, string(body))
	}

	return nil
}

// SaveState persists agent state to disk for recovery
func (a *ProvisioningAgent) SaveState(state *AgentState) error {
	if err := os.MkdirAll(filepath.Dir(StateFile), 0750); err != nil {
		return fmt.Errorf("failed to create state directory: %w", err)
	}

	data, err := json.MarshalIndent(state, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal state: %w", err)
	}

	// Atomic write using temp file + rename
	tmpFile := StateFile + ".tmp"
	if err := os.WriteFile(tmpFile, data, 0640); err != nil {
		return fmt.Errorf("failed to write temp state file: %w", err)
	}
	if err := os.Rename(tmpFile, StateFile); err != nil {
		os.Remove(tmpFile)
		return fmt.Errorf("failed to rename state file: %w", err)
	}

	return nil
}

// LoadState loads persisted agent state from disk
func (a *ProvisioningAgent) LoadState() (*AgentState, error) {
	data, err := os.ReadFile(StateFile)
	if err != nil {
		return nil, err
	}

	var state AgentState
	if err := json.Unmarshal(data, &state); err != nil {
		return nil, fmt.Errorf("failed to unmarshal state: %w", err)
	}
	return &state, nil
}

func (a *ProvisioningAgent) InstallPrerequisites() error {
	a.Logger.Info("Checking prerequisites")
	a.SendHeartbeat("installing", "healthy", "Checking prerequisites...", nil)

	// Check if Docker is installed
	if _, err := exec.LookPath("docker"); err != nil {
		a.SendHeartbeat("installing", "error", "Docker not found. Please run the install script first.", nil)
		return fmt.Errorf("%w: docker not found - please run the install script first", ErrDockerNotReady)
	}

	// Check if nvidia-smi is available
	if _, err := exec.LookPath("nvidia-smi"); err != nil {
		a.SendHeartbeat("installing", "error", "nvidia-smi not found. NVIDIA driver must be installed.", nil)
		return fmt.Errorf("%w: nvidia-smi not found - NVIDIA driver must be installed manually", ErrGPUNotDetected)
	}

	// Wait for Docker to be ready
	if err := a.waitForDocker(); err != nil {
		return fmt.Errorf("%w: %v", ErrDockerNotReady, err)
	}

	// Configure profiling permissions for advanced metrics (if DCGM is installed)
	a.configureProfilingPermissions()

	a.Logger.Info("Prerequisites verified")
	a.SendHeartbeat("installing", "healthy", "Prerequisites verified", nil)
	return nil
}

// configureProfilingPermissions sets up NVIDIA profiling permissions if DCGM is installed
func (a *ProvisioningAgent) configureProfilingPermissions() {
	dcgmInstalled := false
	if _, err := exec.LookPath("dcgmi"); err == nil {
		dcgmInstalled = true
	} else if _, err := exec.LookPath("dcgm"); err == nil {
		dcgmInstalled = true
	} else {
		cmd := exec.CommandContext(a.ctx, "dpkg", "-l", "datacenter-gpu-manager")
		if cmd.Run() == nil {
			dcgmInstalled = true
		}
	}

	if !dcgmInstalled {
		return
	}

	// Check if profiling permissions are configured using Go native file operations
	configPath := "/etc/modprobe.d/omniference-nvidia.conf"
	content, err := os.ReadFile(configPath)
	if err != nil || !strings.Contains(string(content), "NVreg_RestrictProfilingToAdminUsers") {
		a.SendHeartbeat("installing", "healthy", "Configuring profiling permissions for advanced metrics...", nil)

		// Create profiling config using Go file operations (no shell injection)
		configContent := "options nvidia NVreg_RestrictProfilingToAdminUsers=0\n"
		if err := os.WriteFile(configPath, []byte(configContent), 0644); err != nil {
			a.Logger.Warn("Failed to configure profiling permissions", zap.Error(err))
			a.SendHeartbeat("installing", "warning", "Failed to configure profiling permissions (non-critical)", nil)
		} else {
			// Update initramfs (no shell)
			cmd := exec.CommandContext(a.ctx, "update-initramfs", "-u")
			cmd.Run() // Ignore errors, non-critical
			a.SendHeartbeat("installing", "healthy", "Profiling permissions configured (reboot required for full effect)", nil)
		}
	} else {
		// Check if reboot is needed
		paramsContent, err := os.ReadFile("/proc/driver/nvidia/params")
		if err == nil {
			if strings.Contains(string(paramsContent), "RmProfilingAdminOnly: 1") {
				a.SendHeartbeat("installing", "warning", "Profiling permissions configured but reboot needed (RmProfilingAdminOnly=1)", nil)
			} else {
				a.SendHeartbeat("installing", "healthy", "Profiling permissions active (RmProfilingAdminOnly=0)", nil)
			}
		}
	}

	// Ensure DCGM service is running (no shell)
	cmd := exec.CommandContext(a.ctx, "systemctl", "is-active", "--quiet", "dcgm")
	if cmd.Run() != nil {
		cmd = exec.CommandContext(a.ctx, "systemctl", "start", "dcgm")
		if cmd.Run() == nil {
			a.SendHeartbeat("installing", "healthy", "DCGM service started", nil)
		}
	}
}

func (a *ProvisioningAgent) waitForDocker() error {
	maxAttempts := 30
	for i := 0; i < maxAttempts; i++ {
		select {
		case <-a.ctx.Done():
			return a.ctx.Err()
		default:
		}

		cmd := exec.CommandContext(a.ctx, "docker", "info")
		if err := cmd.Run(); err == nil {
			return nil
		}
		time.Sleep(2 * time.Second)
	}
	return fmt.Errorf("docker did not become ready after %d attempts", maxAttempts)
}

// fixDockerNvidiaDefaultRuntime fixes Docker configuration on systems where
// "default-runtime": "nvidia" causes CUDA symlink conflicts (e.g., Scaleway GPU OS).
// The nvidia runtime creates libcuda.so symlinks in container overlays, which fails
// on scratch/overlay filesystems when multiple containers start.
// This fix removes the default-runtime setting, keeping nvidia available but not default.
// Safe to run on Lambda/other providers as it's a no-op if the setting isn't present.
func (a *ProvisioningAgent) fixDockerNvidiaDefaultRuntime() error {
	const daemonConfigPath = "/etc/docker/daemon.json"
	
	// Read current config
	data, err := os.ReadFile(daemonConfigPath)
	if err != nil {
		if os.IsNotExist(err) {
			a.Logger.Debug("No daemon.json found, skipping nvidia runtime fix")
			return nil
		}
		return fmt.Errorf("failed to read daemon.json: %w", err)
	}
	
	// Check if default-runtime is set to nvidia
	var config map[string]interface{}
	if err := json.Unmarshal(data, &config); err != nil {
		a.Logger.Warn("Failed to parse daemon.json, skipping nvidia runtime fix", zap.Error(err))
		return nil
	}
	
	defaultRuntime, ok := config["default-runtime"]
	if !ok {
		a.Logger.Debug("No default-runtime set, no fix needed")
		return nil
	}
	
	if defaultRuntime != "nvidia" {
		a.Logger.Debug("Default runtime is not nvidia, no fix needed", zap.String("runtime", fmt.Sprintf("%v", defaultRuntime)))
		return nil
	}
	
	// Remove the default-runtime key to use runc as default
	a.Logger.Info("Detected default-runtime: nvidia - fixing to prevent CUDA symlink conflicts")
	delete(config, "default-runtime")
	
	// Write updated config
	newData, err := json.MarshalIndent(config, "", "    ")
	if err != nil {
		return fmt.Errorf("failed to marshal new daemon.json: %w", err)
	}
	
	if err := os.WriteFile(daemonConfigPath, newData, 0644); err != nil {
		return fmt.Errorf("failed to write daemon.json: %w", err)
	}
	
	a.Logger.Info("Updated Docker daemon.json - removed default-runtime: nvidia")
	
	// Restart Docker to apply changes
	a.Logger.Info("Restarting Docker to apply configuration changes")
	cmd := exec.CommandContext(a.ctx, "systemctl", "restart", "docker")
	if output, err := cmd.CombinedOutput(); err != nil {
		a.Logger.Warn("Failed to restart Docker via systemctl", zap.Error(err), zap.String("output", string(output)))
		// Try service command as fallback
		cmd = exec.CommandContext(a.ctx, "service", "docker", "restart")
		if output, err := cmd.CombinedOutput(); err != nil {
			return fmt.Errorf("failed to restart Docker: %w, output: %s", err, string(output))
		}
	}
	
	// Wait for Docker to be ready again
	a.Logger.Info("Waiting for Docker to be ready after restart")
	time.Sleep(5 * time.Second)
	if err := a.waitForDocker(); err != nil {
		return fmt.Errorf("Docker failed to restart after config fix: %w", err)
	}
	
	a.Logger.Info("Docker configuration fixed successfully - nvidia runtime available but not default")
	return nil
}

// DeployStack deploys the telemetry stack with atomic operations and rollback support
func (a *ProvisioningAgent) DeployStack() error {
	a.Logger.Info("Deploying telemetry stack")
	a.SendHeartbeat("deploying", "healthy", "Deploying telemetry stack...", nil)

	if a.DeploymentConfig == nil {
		return fmt.Errorf("%w: deployment config not loaded", ErrDeploymentFailed)
	}

	deploymentDir := a.getDeploymentDir()

	// Create parent directory
	if err := os.MkdirAll(filepath.Dir(deploymentDir), 0750); err != nil {
		return fmt.Errorf("failed to create deployment root: %w", err)
	}

	// Backup existing deployment for rollback
	backupPath := deploymentDir + ".backup." + time.Now().Format("20060102-150405")
	deploymentFailed := true // Track success for rollback

	defer func() {
		if deploymentFailed && backupPath != "" {
			// Rollback: restore backup
			os.RemoveAll(deploymentDir)
			if _, err := os.Stat(backupPath); err == nil {
				if err := os.Rename(backupPath, deploymentDir); err != nil {
					a.Logger.Warn("Failed to rollback deployment", zap.Error(err))
				} else {
					a.Logger.Info("Deployment failed - rolled back to previous version")
				}
			}
		} else if !deploymentFailed {
			// Success: cleanup old backup
			os.RemoveAll(backupPath)
		}
	}()

	// Backup if exists
	if _, err := os.Stat(deploymentDir); err == nil {
		if err := os.Rename(deploymentDir, backupPath); err != nil {
			return fmt.Errorf("failed to backup existing deployment: %w", err)
		}
	}

	if err := os.MkdirAll(deploymentDir, 0755); err != nil {
		return fmt.Errorf("failed to create directory: %w", err)
	}

	// Write docker-compose.yml
	composePath := filepath.Join(deploymentDir, "docker-compose.yml")
	if err := os.WriteFile(composePath, []byte(a.DeploymentConfig.DockerCompose), 0644); err != nil {
		return fmt.Errorf("failed to write docker-compose.yml: %w", err)
	}

	// Write prometheus.yml
	prometheusPath := filepath.Join(deploymentDir, "prometheus.yml")
	if err := os.WriteFile(prometheusPath, []byte(a.DeploymentConfig.PrometheusConfig), 0644); err != nil {
		return fmt.Errorf("failed to write prometheus.yml: %w", err)
	}

	if err := a.writeDeploymentArtifacts(deploymentDir); err != nil {
		return err
	}

	// Wait for Docker to be ready before deploying
	if err := a.waitForDocker(); err != nil {
		return fmt.Errorf("%w: %v", ErrDockerNotReady, err)
	}

	// Fix Docker configuration if nvidia is set as default runtime
	// This is needed for Scaleway GPU OS which pre-configures "default-runtime": "nvidia"
	// causing CUDA symlink conflicts when multiple containers start
	if err := a.fixDockerNvidiaDefaultRuntime(); err != nil {
		a.Logger.Warn("Failed to fix Docker nvidia default runtime", zap.Error(err))
		// Continue anyway - the sequential start fallback may still work
	}

	// If profiling is enabled, restart DCGM service
	if strings.Contains(a.DeploymentConfig.DockerCompose, "DCGM_EXPORTER_ENABLE_PROFILING: \"true\"") {
		a.restartDCGMService()
	}

	// Stop any existing containers first to avoid CUDA library symlink conflicts
	// This prevents "device or resource busy" errors when NVIDIA Container Toolkit
	// tries to create libcuda.so.1 symlinks in multiple containers simultaneously
	// This fix works for both Lambda and Scaleway instances
	a.Logger.Info("Stopping existing containers to prevent CUDA symlink conflicts")
	cmd := exec.CommandContext(a.ctx, "docker", "compose", "down", "--remove-orphans", "--timeout", "10")
	cmd.Dir = deploymentDir
	if output, err := cmd.CombinedOutput(); err != nil {
		a.Logger.Debug("docker compose down completed (containers may not have existed)", zap.String("output", string(output)))
	}
	
	// Wait for containers to fully stop and CUDA resources to be released
	// Longer wait helps with Scaleway's overlay filesystem while not affecting Lambda
	time.Sleep(5 * time.Second)
	
	// Verify containers are stopped - this ensures compatibility with both providers
	cmd = exec.CommandContext(a.ctx, "docker", "compose", "ps", "--quiet")
	cmd.Dir = deploymentDir
	if output, err := cmd.CombinedOutput(); err == nil && len(strings.TrimSpace(string(output))) > 0 {
		a.Logger.Warn("Some containers still running, forcing stop with kill")
		// Force kill any remaining containers (works for both Lambda and Scaleway)
		cmd := exec.CommandContext(a.ctx, "docker", "compose", "kill")
		cmd.Dir = deploymentDir
		cmd.Run()
		cmd = exec.CommandContext(a.ctx, "docker", "compose", "rm", "-f")
		cmd.Dir = deploymentDir
		cmd.Run()
		time.Sleep(3 * time.Second)
	}

	// Start Docker Compose with retry logic (no shell injection)
	// First attempt: try normal parallel start (works for Lambda)
	// If CUDA conflict detected, switch to sequential start (needed for Scaleway)
	maxRetries := 5
	useSequentialStart := false
	var lastErr error
	
	for i := 0; i < maxRetries; i++ {
		select {
		case <-a.ctx.Done():
			return a.ctx.Err()
		default:
		}

		var output []byte
		var err error
		
		if useSequentialStart {
			// Sequential start: start containers one at a time to avoid CUDA symlink conflicts
			// This is needed for Scaleway but safe for Lambda too
			a.Logger.Info("Starting containers sequentially to avoid CUDA symlink conflicts")
			output, err = a.startContainersSequentially(deploymentDir)
		} else {
			// Normal parallel start (works for Lambda, may fail on Scaleway)
			cmd := exec.CommandContext(a.ctx, "docker", "compose", "up", "-d")
			cmd.Dir = deploymentDir
			output, err = cmd.CombinedOutput()
		}
		
		if err == nil {
			// Check for profiling errors and auto-disable if needed
			if strings.Contains(a.DeploymentConfig.DockerCompose, "DCGM_EXPORTER_ENABLE_PROFILING: \"true\"") {
				a.handleProfilingErrors(deploymentDir)
			}

			// Verify deployment health
			if err := a.VerifyDeployment(30 * time.Second); err != nil {
				a.Logger.Warn("Deployment verification failed", zap.Error(err))
			}

			deploymentFailed = false
			a.SendHeartbeat("deploying", "healthy", "Stack deployed successfully", nil)
			return nil
		}
		
		// Check if error is due to CUDA library symlink conflict
		// This handles both Lambda (rare) and Scaleway (more common) instances
		outputStr := string(output)
		if strings.Contains(outputStr, "device or resource busy") || strings.Contains(outputStr, "libcuda.so") {
			// Switch to sequential start on first CUDA conflict detection
			if !useSequentialStart {
				a.Logger.Info("CUDA symlink conflict detected, switching to sequential container startup")
				useSequentialStart = true
			}
			
			a.Logger.Warn("CUDA library symlink conflict detected, stopping containers and retrying",
				zap.Int("attempt", i+1),
				zap.Int("max_retries", maxRetries),
				zap.Bool("sequential_start", useSequentialStart),
				zap.String("output", outputStr))
			
			// Aggressive cleanup: kill, remove, then down (works for both providers)
			cmd := exec.CommandContext(a.ctx, "docker", "compose", "kill")
			cmd.Dir = deploymentDir
			cmd.Run()
			cmd = exec.CommandContext(a.ctx, "docker", "compose", "rm", "-f")
			cmd.Dir = deploymentDir
			cmd.Run()
			cmd = exec.CommandContext(a.ctx, "docker", "compose", "down", "--remove-orphans", "--timeout", "10")
			cmd.Dir = deploymentDir
			if output, err := cmd.CombinedOutput(); err != nil {
				a.Logger.Debug("docker compose down output", zap.String("output", string(output)))
			}
			
			// Progressive wait time: longer for Scaleway overlay filesystem, safe for Lambda
			// Starts at 7s, increases by 3s each retry (7s, 10s, 13s, 16s)
			waitTime := time.Duration(7+i*3) * time.Second
			a.Logger.Info("Waiting for CUDA resources to be released", zap.Duration("wait_time", waitTime))
			time.Sleep(waitTime)
		}
		
		lastErr = fmt.Errorf("%w: docker compose failed: %s", ErrDeploymentFailed, outputStr)
		if i < maxRetries-1 {
			time.Sleep(time.Duration(i+1) * 2 * time.Second)
		}
	}

	a.SendHeartbeat("deploying", "error", lastErr.Error(), nil)
	return lastErr
}

// startContainersSequentially starts containers one at a time to avoid CUDA symlink conflicts
// This is needed for Scaleway instances but safe for Lambda too
// Prioritizes non-CUDA containers (token-exporter, prometheus) first
func (a *ProvisioningAgent) startContainersSequentially(deploymentDir string) ([]byte, error) {
	// Get list of services from docker-compose
	// We don't create all containers first - we create and start them one at a time
	// This prevents Docker Compose from starting dependencies
	cmd := exec.CommandContext(a.ctx, "docker", "compose", "config", "--services")
	cmd.Dir = deploymentDir
	output, err := cmd.Output()
	if err != nil {
		return output, fmt.Errorf("failed to get service list: %w", err)
	}
	
	allServices := strings.Fields(strings.TrimSpace(string(output)))
	if len(allServices) == 0 {
		return nil, fmt.Errorf("no services found in docker-compose.yml")
	}
	
	// Prioritize non-CUDA containers first to avoid symlink conflicts
	// Non-CUDA services don't trigger NVIDIA Container Toolkit symlink creation
	nonCUDAServices := []string{}
	cudaServices := []string{}
	
	for _, service := range allServices {
		// Services that don't use CUDA/NVIDIA runtime
		if service == "token-exporter" || service == "prometheus" {
			nonCUDAServices = append(nonCUDAServices, service)
		} else {
			// All other services likely use CUDA (nvidia-smi-exporter, dcgm-exporter, dcgm-health-exporter)
			cudaServices = append(cudaServices, service)
		}
	}
	
	// Combine: non-CUDA first, then CUDA services
	services := append(nonCUDAServices, cudaServices...)
	
	a.Logger.Info("Starting containers sequentially with priority",
		zap.Int("non_cuda_count", len(nonCUDAServices)),
		zap.Int("cuda_count", len(cudaServices)),
		zap.Strings("order", services))
	
	// Start each service sequentially with appropriate delays
	var allOutput []byte
	for i, service := range services {
		a.Logger.Info("Starting container sequentially",
			zap.String("service", service),
			zap.Int("index", i+1),
			zap.Int("total", len(services)),
			zap.Bool("is_cuda", i >= len(nonCUDAServices)))
		
		// Use 'up -d --no-deps' to create and start one service at a time
		// --no-deps: Don't start dependencies (prevents Docker from starting CUDA containers when starting prometheus)
		// This creates the container if it doesn't exist, or starts it if it does
		cmd := exec.CommandContext(a.ctx, "docker", "compose", "up", "-d", "--no-deps", service)
		cmd.Dir = deploymentDir
		output, err := cmd.CombinedOutput()
		allOutput = append(allOutput, output...)
		
		if err != nil {
			// If a service fails, try to clean up and return error
			a.Logger.Warn("Failed to start service, cleaning up",
				zap.String("service", service),
				zap.String("error", string(output)))
			cmd := exec.CommandContext(a.ctx, "docker", "compose", "down", "--remove-orphans")
			cmd.Dir = deploymentDir
			cmd.Run()
			return allOutput, fmt.Errorf("failed to start service %s: %w", service, err)
		}
		
		// Wait between container starts:
		// - Short delay (1s) between non-CUDA containers
		// - Longer delay (8s) before first CUDA container (after non-CUDA) - gives overlay filesystem time to release
		// - Medium delay (5s) between CUDA containers
		if i < len(services)-1 {
			if i == len(nonCUDAServices)-1 && len(cudaServices) > 0 {
				// Transition from non-CUDA to CUDA: longer wait for Scaleway overlay filesystem
				waitTime := 8 * time.Second
				a.Logger.Info("Waiting before starting CUDA containers", zap.Duration("wait", waitTime))
				time.Sleep(waitTime)
			} else if i >= len(nonCUDAServices) {
				// Between CUDA containers: medium wait
				time.Sleep(5 * time.Second)
			} else {
				// Between non-CUDA containers: short wait
				time.Sleep(1 * time.Second)
			}
		}
	}
	
	a.Logger.Info("All containers started sequentially", zap.Int("count", len(services)))
	return allOutput, nil
}

// restartDCGMService restarts the DCGM service for profiling initialization
func (a *ProvisioningAgent) restartDCGMService() {
	a.SendHeartbeat("deploying", "healthy", "Restarting DCGM service for profiling initialization...", nil)
	a.Logger.Info("Profiling enabled - restarting DCGM service")

	// Try dcgm service first
	cmd := exec.CommandContext(a.ctx, "systemctl", "list-unit-files", "--type=service", "dcgm.service")
	if cmd.Run() == nil {
		cmd = exec.CommandContext(a.ctx, "systemctl", "restart", "dcgm")
		if output, err := cmd.CombinedOutput(); err != nil {
			a.Logger.Warn("Failed to restart DCGM service", zap.String("output", string(output)))
		} else {
			a.Logger.Info("DCGM service restarted successfully")
			time.Sleep(2 * time.Second)
			return
		}
	}

	// Try nvidia-dcgm service
	cmd = exec.CommandContext(a.ctx, "systemctl", "list-unit-files", "--type=service", "nvidia-dcgm.service")
	if cmd.Run() == nil {
		cmd = exec.CommandContext(a.ctx, "systemctl", "restart", "nvidia-dcgm")
		if output, err := cmd.CombinedOutput(); err != nil {
			a.Logger.Warn("Failed to restart nvidia-dcgm service", zap.String("output", string(output)))
		} else {
			a.Logger.Info("nvidia-dcgm service restarted successfully")
			time.Sleep(2 * time.Second)
		}
	}
}

// handleProfilingErrors checks for DCGM profiling errors and auto-disables if needed
func (a *ProvisioningAgent) handleProfilingErrors(deploymentDir string) {
	time.Sleep(8 * time.Second) // Wait for containers to start

	// Check DCGM exporter logs (no shell injection)
	cmd := exec.CommandContext(a.ctx, "docker", "compose", "logs", "--tail=30", "dcgm-exporter")
	cmd.Dir = deploymentDir
	logsOutput, err := cmd.CombinedOutput()
	if err != nil {
		return
	}

	logsStr := string(logsOutput)
	hasProfilingError := strings.Contains(logsStr, "Profiling module returned an unrecoverable error") ||
		strings.Contains(logsStr, "Failed to watch metrics")

	if !hasProfilingError {
		return
	}

	a.Logger.Warn("DCGM exporter crashing due to profiling errors, disabling profiling")
	a.SendHeartbeat("deploying", "healthy", "Disabling profiling due to DCGM errors...", nil)

	// Stop and remove DCGM exporter container (no shell)
	cmd = exec.CommandContext(a.ctx, "docker", "compose", "stop", "dcgm-exporter")
	cmd.Dir = deploymentDir
	cmd.Run()

	cmd = exec.CommandContext(a.ctx, "docker", "compose", "rm", "-f", "dcgm-exporter")
	cmd.Dir = deploymentDir
	cmd.Run()

	// Remove profiling metrics from CSV using Go native file operations (no sed/shell)
	collectorsPath := filepath.Join(deploymentDir, "dcgm-collectors.csv")
	if content, err := os.ReadFile(collectorsPath); err == nil {
		lines := strings.Split(string(content), "\n")
		filtered := make([]string, 0, len(lines))
		for _, line := range lines {
			if !strings.Contains(line, "DCGM_FI_PROF") {
				filtered = append(filtered, line)
			}
		}
		os.WriteFile(collectorsPath, []byte(strings.Join(filtered, "\n")), 0644)
		a.Logger.Info("Removed profiling metrics from collectors CSV")
	}

	// Disable profiling in docker-compose.yml using Go native file operations (no sed/shell)
	composePath := filepath.Join(deploymentDir, "docker-compose.yml")
	if content, err := os.ReadFile(composePath); err == nil {
		newContent := strings.ReplaceAll(string(content),
			`DCGM_EXPORTER_ENABLE_PROFILING: "true"`,
			`DCGM_EXPORTER_ENABLE_PROFILING: "false"`)
		os.WriteFile(composePath, []byte(newContent), 0644)
		a.Logger.Info("Disabled profiling in docker-compose.yml")
	}

	// Restart DCGM exporter without profiling (no shell)
	cmd = exec.CommandContext(a.ctx, "docker", "compose", "up", "-d", "dcgm-exporter")
	cmd.Dir = deploymentDir
	if output, err := cmd.CombinedOutput(); err != nil {
		a.Logger.Warn("Failed to restart DCGM exporter", zap.String("output", string(output)))
	} else {
		a.Logger.Info("DCGM exporter restarted without profiling")
		time.Sleep(3 * time.Second)
	}

	a.SendHeartbeat("deploying", "healthy", "Profiling disabled due to DCGM errors. Standard metrics available.", nil)
}

// VerifyDeployment waits for containers to become healthy
func (a *ProvisioningAgent) VerifyDeployment(timeout time.Duration) error {
	ctx, cancel := context.WithTimeout(a.ctx, timeout)
	defer cancel()

	ticker := time.NewTicker(2 * time.Second)
	defer ticker.Stop()

	deploymentDir := a.getDeploymentDir()

	for {
		select {
		case <-ticker.C:
			cmd := exec.CommandContext(ctx, "docker", "compose", "ps", "--format", "json")
			cmd.Dir = deploymentDir
			output, err := cmd.Output()
			if err != nil {
				continue
			}

			// Parse JSON output (may be multiple JSON objects, one per line)
			lines := strings.Split(strings.TrimSpace(string(output)), "\n")
			allHealthy := true
			containerCount := 0

			for _, line := range lines {
				if line == "" {
					continue
				}
				var container map[string]interface{}
				if err := json.Unmarshal([]byte(line), &container); err != nil {
					continue
				}
				containerCount++
				state, ok := container["State"].(string)
				if !ok || state != "running" {
					allHealthy = false
				}
			}

			if allHealthy && containerCount > 0 {
				a.Logger.Info("All containers verified healthy", zap.Int("count", containerCount))
				return nil
			}

		case <-ctx.Done():
			return errors.New("timeout waiting for containers to become healthy")
		}
	}
}

func (a *ProvisioningAgent) writeDeploymentArtifacts(dir string) error {
	files := []struct {
		name    string
		content string
		mode    os.FileMode
	}{
		{"dcgm-collectors.csv", a.DeploymentConfig.DCGMCollectors, 0644},
		{"nvidia-smi-exporter.py", a.DeploymentConfig.NvidiaSMIExporter, 0755},
		{"dcgm-health-exporter.py", a.DeploymentConfig.DCGMHealthExporter, 0755},
		{"token-exporter.py", a.DeploymentConfig.TokenExporter, 0755},
	}

	for _, file := range files {
		if file.content == "" {
			continue
		}
		path := filepath.Join(dir, file.name)
		if err := os.WriteFile(path, []byte(file.content), file.mode); err != nil {
			return fmt.Errorf("failed to write %s: %w", file.name, err)
		}
	}

	return nil
}

// Shutdown performs graceful shutdown
func (a *ProvisioningAgent) Shutdown() {
	a.Logger.Info("Sending shutdown heartbeat")
	a.SendHeartbeat("stopped", "healthy", "Agent shutting down", nil)
	a.Logger.Sync()
	a.cancel()
}

func main() {
	// Must run as root for Docker and system operations
	if os.Geteuid() != 0 {
		fmt.Fprintln(os.Stderr, "ERROR: Must run as root. Use systemd service or run with sudo.")
		os.Exit(1)
	}

	// Acquire lock to ensure single instance
	lock := flock.New(LockFile)
	locked, err := lock.TryLock()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to acquire lock: %v\n", err)
		os.Exit(1)
	}
	if !locked {
		fmt.Fprintln(os.Stderr, "Another instance is already running")
		os.Exit(1)
	}
	defer lock.Unlock()

	// Create root context
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Create agent
	agent, err := NewProvisioningAgent(ctx)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Error creating agent: %v\n", err)
		os.Exit(1)
	}
	defer agent.Shutdown()

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		sig := <-sigChan
		agent.Logger.Info("Received shutdown signal", zap.String("signal", sig.String()))
		cancel()
	}()

	// Install prerequisites
	if err := agent.InstallPrerequisites(); err != nil {
		agent.SendHeartbeat("installing", "error", err.Error(), nil)
		agent.Logger.Error("Error installing prerequisites", zap.Error(err))
		os.Exit(1)
	}

	// Check if DCGM is installed to enable profiling metrics
	enableProfiling := false
	dcgmImage, err := agent.detectDCGMImage()
	if err == nil && dcgmImage != "" {
		enableProfiling = true
		agent.Logger.Info("DCGM detected, enabling profiling metrics",
			zap.String("image", dcgmImage))
	} else {
		// Try to check if DCGM is installed but detection failed
		if _, err := exec.LookPath("dcgmi"); err == nil {
			enableProfiling = true
			agent.Logger.Info("DCGM command found but version detection failed - enabling profiling anyway")
		} else {
			agent.Logger.Info("DCGM not detected - profiling metrics will not be available")
		}
	}

	// Fetch deployment config
	if err := agent.FetchDeploymentConfig(5, enableProfiling); err != nil {
		agent.SendHeartbeat("deploying", "error", err.Error(), nil)
		agent.Logger.Error("Error fetching deployment config", zap.Error(err))
		os.Exit(1)
	}

	// Validate deployment config
	if err := agent.ValidateDeploymentConfig(); err != nil {
		agent.Logger.Error("Invalid deployment config", zap.Error(err))
		os.Exit(1)
	}

	// Deploy stack
	if err := agent.DeployStack(); err != nil {
		agent.SendHeartbeat("deploying", "error", err.Error(), nil)
		agent.Logger.Error("Error deploying stack", zap.Error(err))
		os.Exit(1)
	}

	// Save state
	agent.SaveState(&AgentState{
		Phase:         "running",
		Status:        "healthy",
		LastHeartbeat: time.Now(),
		DeploymentDir: agent.getDeploymentDir(),
		Version:       AgentVersion,
	})

	// Send running heartbeat
	agent.SendHeartbeat("running", "healthy", "Telemetry stack is running", nil)
	agent.Logger.Info("Telemetry stack deployed successfully, entering heartbeat loop")

	// Heartbeat loop with graceful shutdown
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if err := agent.SendHeartbeat("running", "healthy", "Telemetry stack is running", nil); err != nil {
				agent.Logger.Warn("Failed to send heartbeat", zap.Error(err))
			}
		case <-ctx.Done():
			agent.Logger.Info("Shutdown complete")
			return
		}
	}
}
