#!/bin/bash
# Helper script to set up Nebius CLI profile

set -e

echo "Nebius CLI Profile Setup"
echo "========================"
echo ""

# Check if nebius is in PATH
if ! command -v nebius &> /dev/null; then
    export PATH=$PATH:$HOME/.nebius/bin
    if ! command -v nebius &> /dev/null; then
        echo "Error: nebius CLI not found. Please install it first."
        exit 1
    fi
fi

echo "Choose authentication method:"
echo "1) Service Account (recommended for servers - no browser needed)"
echo "2) OAuth with browser (requires SSH port forwarding)"
echo ""
read -p "Enter choice [1 or 2]: " choice

case $choice in
    1)
        echo ""
        echo "Service Account Authentication"
        echo "=============================="
        echo "You'll need:"
        echo "  - Service Account ID"
        echo "  - Key ID (authorized key ID)"
        echo "  - Private Key file path (PEM format)"
        echo ""
        read -p "Service Account ID: " SERVICE_ACCOUNT_ID
        read -p "Key ID: " KEY_ID
        read -p "Private Key file path: " PRIVATE_KEY_PATH
        
        if [ ! -f "$PRIVATE_KEY_PATH" ]; then
            echo "Error: Private key file not found: $PRIVATE_KEY_PATH"
            exit 1
        fi
        
        echo ""
        echo "Creating profile 'madhur'..."
        nebius profile create madhur \
            --service-account-id="$SERVICE_ACCOUNT_ID" \
            --public-key-id="$KEY_ID" \
            --private-key-file-path="$PRIVATE_KEY_PATH" \
            --endpoint=api.nebius.cloud \
            --federation-endpoint=auth.nebius.com
        
        echo ""
        echo "✅ Profile created successfully!"
        ;;
    2)
        echo ""
        echo "OAuth Authentication"
        echo "===================="
        echo ""
        echo "⚠️  IMPORTANT: You need to set up SSH port forwarding first!"
        echo ""
        echo "On your LOCAL machine, run:"
        echo "  ssh -L 39683:localhost:39683 user@your-server-ip"
        echo ""
        echo "Then in that SSH session, run this script again and choose option 2."
        echo ""
        read -p "Have you set up port forwarding? [y/N]: " confirm
        
        if [[ ! $confirm =~ ^[Yy]$ ]]; then
            echo "Please set up port forwarding first, then run this script again."
            exit 1
        fi
        
        echo ""
        echo "Creating profile 'madhur' with --no-browser..."
        nebius profile create madhur --no-browser
        
        echo ""
        echo "✅ Profile creation initiated!"
        echo "Copy the authentication URL and open it in your LOCAL browser."
        ;;
    *)
        echo "Invalid choice. Please run the script again."
        exit 1
        ;;
esac

echo ""
echo "Verifying profile..."
nebius profile list

echo ""
echo "To use this profile:"
echo "  nebius --profile madhur <command>"
echo ""
echo "Or set it as default:"
echo "  export NEBIUS_PROFILE=madhur"



