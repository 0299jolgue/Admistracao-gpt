# Android Admin

Protótipo funcional de gestão de dispositivos Android explicitamente autorizados, desenhado para execução em Linux/ShardCloud.

## Arranque

O ponto de entrada é único:

```bash
python starter.py
```

O starter prepara diretórios, inicializa SQLite, cria o administrador inicial quando necessário, tenta instalar dependências Python em falta e arranca o servidor diretamente em `0.0.0.0:80`.

A aplicação não usa 8080 como fallback ou porta interna.

## URL público

O backend calcula `public_base_url` usando `X-Forwarded-Host`, `Host`, `X-Forwarded-Proto` e o host recebido. O APK Builder não pede URL manualmente.

## Credenciais iniciais do protótipo

Utilizador: `admin`

Password: `admin123`

Altere estas credenciais antes de um ambiente real.

## Funcionalidades

- autenticação e sessão administrativa;
- dashboard com estado dos dispositivos, comandos e atividade;
- enrollment com código/token e revogação;
- WebSocket browser ↔ servidor ↔ agente;
- heartbeat e reconexão;
- comandos autorizados e respostas;
- mensagens e notificações;
- logs e histórico;
- Demo Mode persistente e identificado;
- APK Builder com autodeteção de Java/Gradle/Android SDK;
- estado explícito `BUILD TOOLCHAIN UNAVAILABLE` quando a infraestrutura não suporta build Android;
- health check em `/health`;
- SQLite persistente em `database/platform.db`.

## Android

`android/agent` contém um esqueleto de agente Android orientado a consentimento. O agente deve obter permissões oficiais do Android, mostrar claramente quando a captura de ecrã ou outra função estiver ativa e nunca ocultar a inscrição.

A captura de ecrã deve usar as APIs oficiais e o consentimento do utilizador. O protótipo não implementa bypass de permissões.

## Limitações do protótipo

O código de servidor está funcional, mas o build de APK só será realizado se a infraestrutura tiver Java, Gradle e Android SDK configurados. Em ShardCloud, o sistema deteta a indisponibilidade e não finge uma compilação bem-sucedida.

Para produção, recomenda-se substituir o segredo de sessão, adicionar HTTPS-only cookies quando o proxy estiver confirmado, restringir `forwarded_allow_ips` ao proxy da hospedagem e configurar um pipeline dedicado de build Android.
