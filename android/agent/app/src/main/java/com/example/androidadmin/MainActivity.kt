package com.example.androidadmin

import android.app.Activity
import android.os.Bundle
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Button
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import okhttp3.*
import org.json.JSONObject
import java.util.concurrent.TimeUnit

class MainActivity : AppCompatActivity() {
    private var socket: WebSocket? = null
    private lateinit var state: TextView
    private val prefs by lazy { getSharedPreferences("agent", MODE_PRIVATE) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        val root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(32,32,32,32) }
        state = TextView(this).apply { textSize = 18f; text = "Android Admin Agent\nA aguardar inscrição autorizada." }
        val connect = Button(this).apply { text = "Ligar ao servidor"; setOnClickListener { connectIfConfigured() } }
        val screen = Button(this).apply { text = "Pré-visualização de captura (consentimento)"; setOnClickListener { Toast.makeText(this@MainActivity, "A captura real deve usar MediaProjection e o diálogo oficial de consentimento do Android.", Toast.LENGTH_LONG).show() } }
        root.addView(state); root.addView(connect); root.addView(screen); setContentView(root)
    }

    private fun connectIfConfigured() {
        val base = prefs.getString("server_url", "") ?: ""
        val token = prefs.getString("device_token", "") ?: ""
        val deviceId = prefs.getInt("device_id", 0)
        if (base.isBlank() || token.isBlank() || deviceId == 0) {
            Toast.makeText(this, "Este dispositivo ainda não foi inscrito pelo administrador.", Toast.LENGTH_LONG).show(); return
        }
        val wsUrl = base.replaceFirst("^http", "ws") + "/ws/device/" + deviceId + "?token=" + token
        val client = OkHttpClient.Builder().pingInterval(20, TimeUnit.SECONDS).build()
        socket = client.newWebSocket(Request.Builder().url(wsUrl).build(), object: WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                runOnUiThread { state.text = "Android Admin Agent\nLigado e autorizado." }
                webSocket.send(JSONObject(mapOf("type" to "device.info", "model" to android.os.Build.MODEL, "manufacturer" to android.os.Build.MANUFACTURER, "android_version" to android.os.Build.VERSION.RELEASE, "agent_version" to "1.0.0", "battery" to 0, "network" to "unknown", "ip" to "")).toString())
            }
            override fun onMessage(webSocket: WebSocket, text: String) { handle(text, webSocket) }
            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) { runOnUiThread { state.text = "Ligação indisponível.\n${t.message ?: "erro"}" } }
            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) { runOnUiThread { state.text = "Ligação encerrada." } }
        })
    }

    private fun handle(text: String, webSocket: WebSocket) {
        try {
            val obj = JSONObject(text)
            when (obj.optString("type")) {
                "command" -> {
                    val command = obj.optString("command")
                    if (command == "screen_start") {
                        runOnUiThread { Toast.makeText(this, "O Android deve apresentar o consentimento oficial MediaProjection antes de transmitir o ecrã.", Toast.LENGTH_LONG).show() }
                        webSocket.send(JSONObject(mapOf("type" to "command.result", "command_id" to obj.optInt("command_id"), "status" to "FAILED", "response" to mapOf("reason" to "USER_CONSENT_REQUIRED"))).toString())
                    } else if (command == "screen_stop") {
                        webSocket.send(JSONObject(mapOf("type" to "command.result", "command_id" to obj.optInt("command_id"), "status" to "COMPLETED", "response" to emptyMap<String,String>())).toString())
                    } else {
                        webSocket.send(JSONObject(mapOf("type" to "command.result", "command_id" to obj.optInt("command_id"), "status" to "COMPLETED", "response" to mapOf("accepted" to true, "command" to command))).toString())
                    }
                }
                "message" -> runOnUiThread { Toast.makeText(this, "Mensagem: ${obj.optString("content")}", Toast.LENGTH_LONG).show() }
                "revoked" -> runOnUiThread { state.text = "Acesso revogado pelo administrador." }
            }
        } catch (_: Exception) { }
    }
}
