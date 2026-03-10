#!/bin/bash
# Script to set up domain hosting for the provisioning agent
# This sets up the downloads directory and nginx configuration

set -e

DOMAIN="omniference.com"
DOWNLOADS_DIR="/var/www/omniference/downloads"
NGINX_CONF="/etc/nginx/sites-available/omniference-downloads"

echo "Setting up domain hosting for provisioning agent on ${DOMAIN}..."
echo ""

# Create downloads directory
echo "Creating downloads directory..."
sudo mkdir -p "${DOWNLOADS_DIR}"
sudo chown -R www-data:www-data "${DOWNLOADS_DIR}"
sudo chmod 755 "${DOWNLOADS_DIR}"

# Copy files
echo "Copying files to downloads directory..."
if [ -f "provisioning-agent-linux-amd64" ]; then
    sudo cp provisioning-agent-linux-amd64 "${DOWNLOADS_DIR}/"
    sudo chmod 755 "${DOWNLOADS_DIR}/provisioning-agent-linux-amd64"
    echo "✅ Binary copied"
else
    echo "⚠️  Binary not found. Build it first:"
    echo "   GOOS=linux GOARCH=amd64 go build -o provisioning-agent-linux-amd64 main.go"
fi

if [ -f "install-agent.sh" ]; then
    sudo cp install-agent.sh "${DOWNLOADS_DIR}/"
    sudo chmod 644 "${DOWNLOADS_DIR}/install-agent.sh"
    echo "✅ Install script copied"
fi

# Create nginx configuration
echo "Creating nginx configuration..."
sudo tee "${NGINX_CONF}" > /dev/null <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${DOMAIN};

    # Downloads directory
    location /downloads/ {
        alias ${DOWNLOADS_DIR}/;
        autoindex on;
        add_header Content-Disposition "attachment";
        
        # Security headers
        add_header X-Content-Type-Options "nosniff";
        add_header X-Frame-Options "DENY";
        
        # Allow downloads
        types {
            application/octet-stream bin;
            application/x-executable exe;
            text/plain sh;
        }
    }
}
EOF

# Enable site (if not already enabled)
if [ ! -L "/etc/nginx/sites-enabled/omniference-downloads" ]; then
    echo "Enabling nginx site..."
    sudo ln -s "${NGINX_CONF}" /etc/nginx/sites-enabled/omniference-downloads
fi

# Test nginx configuration
echo "Testing nginx configuration..."
sudo nginx -t

echo ""
echo "✅ Domain hosting setup complete!"
echo ""
echo "Files are available at:"
echo "  - Binary: https://${DOMAIN}/downloads/provisioning-agent-linux-amd64"
echo "  - Install script: https://${DOMAIN}/downloads/install-agent.sh"
echo ""
echo "To apply changes, reload nginx:"
echo "  sudo systemctl reload nginx"
echo ""
echo "To test installation:"
echo "  curl -fsSL https://${DOMAIN}/downloads/install-agent.sh | sudo bash"




