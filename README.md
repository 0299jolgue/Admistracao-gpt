# Admistracao GPT — Android Device Management

Protótipo funcional de gestão de dispositivos Android explicitamente autorizados.

## ShardCloud

O ponto de entrada é:

```bash
python starter.py
```

O servidor arranca diretamente em `0.0.0.0:80`. Não existe fallback para 8080 nem outra porta.

O URL público é descoberto automaticamente através de `PUBLIC_BASE_URL` quando definido ou dos headers `X-Forwarded-Host`, `X-Forwarded-Proto` e `Host`.

## Credenciais iniciais

`admin / admin123` — alterar em produção através das variáveis `ADMIN_USER` e `ADMIN_PASSWORD`.

## Funcionalidades

- autenticação e sessão administrativa
- dashboard responsivo em dark mode
- SQLite persistente criado no primeiro arranque
- dispositivos e enrollment por código de uso limitado
- tokens individuais e revogáveis
- WebSocket em tempo real browser ↔ servidor ↔ agente
- heartbeat/status online-offline
- comandos, mensagens, notificações e logs
- Demo Mode com dispositivos simulados identificados como DEMO
- deteção automática do URL público
- APK Builder com estado explícito quando o toolchain Android não está disponível
- estrutura do agente Android orientada a consentimento e APIs oficiais
- endpoint `/health`

## Segurança e consentimento

Apenas dispositivos inscritos com token individual podem abrir o WebSocket do agente. Captura de ecrã e outras capacidades sensíveis devem depender do consentimento e permissões oficiais do Android. Não há mecanismos ocultos para contornar essas permissões.

## Limitação do APK Builder

O protótipo não finge uma compilação quando Java/Gradle/Android SDK não estão presentes. Nessa situação o painel apresenta `BUILD TOOLCHAIN UNAVAILABLE` e mantém a arquitetura pronta para um ambiente com toolchain compatível.
