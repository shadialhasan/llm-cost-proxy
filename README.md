# 💸 llm-cost-proxy

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Zero Dependency](https://img.shields.io/badge/Dependencies-Standard%20Lib-brightgreen.svg)](https://github.com/MobileConduit)

A reverse proxy microservice for monitoring LLM token consumption, calculating real-time dollar expenditure across major model providers (OpenAI, Anthropic, Google Gemini), and enforcing organization-level budget guards.

## 🚀 Quick Run
```bash
python proxy_server.py
```
Send test request:
```bash
curl -X POST http://localhost:8080 -H "Content-Type: application/json" -d '{"model": "gpt-4o", "messages": "Hello world"}'
```

---

## 👤 Author & Maintainer

**Eng. MHD. Shadi AL-Hasan**  
- **Role:** Executive CTO & Enterprise Solutions Architect  
- **Email:** [mhd.shadi.alhasan@gmail.com](mailto:mhd.shadi.alhasan@gmail.com)  
- **Phone / WhatsApp:** [+963934005922](tel:+963934005922)  
- **Location:** Damascus, Syria  
- **GitHub:** [MobileConduit](https://github.com/MobileConduit)  

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.  
Copyright (c) 2026 **MHD. Shadi AL-Hasan**. All rights reserved.

