# Check driver
nvidia-smi

# Restart DCGM service (if needed)
sudo systemctl restart dcgm

# Run dcgmi dmon
dcgmi dmon -e 1002,1005,203,252,150,155