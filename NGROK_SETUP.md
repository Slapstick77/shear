# Ngrok Setup for Shear App

## Overview
Ngrok creates a secure tunnel to your local Flask server, allowing external services (like PowerApp webhooks) to send HTTP requests to your application.

## Quick Start

1. **Start the app with ngrok tunnel:**
   ```bash
   ./start_with_ngrok.sh
   ```

2. **View your public URL:**
   - Check the terminal output for the ngrok URL
   - Visit http://localhost:4040 for the ngrok web interface
   - View the dashboard at http://localhost:5000 to see the public URL

## Manual Setup

If you prefer to run services separately:

1. **Start Flask app:**
   ```bash
   source venv/bin/activate
   python app.py
   ```

2. **In another terminal, start ngrok:**
   ```bash
   ngrok http 5000
   ```

## Ngrok Features

- **HTTPS tunnel**: Secure public access to your local server
- **Web interface**: Visit http://localhost:4040 to inspect requests
- **Request replay**: Test webhook payloads easily
- **Multiple protocols**: HTTP, HTTPS, TCP support

## PowerApp Integration

1. Copy the ngrok HTTPS URL from the dashboard or terminal
2. Use this URL as your PowerApp webhook endpoint
3. Add `/api/webhook` to the end for webhook receiving
   Example: `https://abc123.ngrok.io/api/webhook`

## Security Notes

- Ngrok tunnels are temporary and change on restart
- Free ngrok accounts have limitations (sessions, bandwidth)
- For production, consider ngrok Pro or direct server deployment

## Troubleshooting

- **Connection refused**: Ensure Flask is running on port 5000
- **Tunnel not working**: Check ngrok installation with `ngrok version`
- **Webhook failures**: Verify the webhook endpoint URL includes the full path
