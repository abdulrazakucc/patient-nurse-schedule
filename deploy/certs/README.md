# Certificates for the bundled HTTPS proxy

Place the hospital's certificate and private key for NeoStay here, then set in `.env`:

```bash
NEOSTAY_TLS=/certs/neostay.crt /certs/neostay.key
```

Everything in this folder except this README is ignored by Git and by Docker
builds. Never commit a private key.
