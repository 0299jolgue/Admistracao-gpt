# Android Agent

Agente de exemplo para dispositivos explicitamente inscritos. O agente deve guardar o token individual recebido no enrollment e abrir o WebSocket em `/ws/device/{device_id}?token=...`.

Funções sensíveis, como captura de ecrã, devem usar APIs oficiais Android e consentimento visível (`MediaProjection`). O agente não deve ocultar a atividade nem contornar permissões.

O `PUBLIC_BASE_URL` do APK Builder é determinado pelo servidor; não é pedido ao utilizador durante a configuração.
