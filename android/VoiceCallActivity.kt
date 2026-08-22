package com.ablogistics.indentassistant.voice

// Reference implementation only — see android/README.md for what to merge into
// your existing Vapi call screen rather than dropping this in verbatim.
//
// API usage confirmed against livekit/client-sdk-android main branch (v2.28, Aug 2026):
// LiveKit.create(), Room.connect(), LocalParticipant.setMicrophoneEnabled(),
// room.events (Flow<RoomEvent>), RoomEvent.{Connected,Disconnected,TrackSubscribed,
// TranscriptionReceived}, TranscriptionSegment.{text,final}. Subscribed audio tracks
// play automatically — no manual audio routing needed for a voice-only call.

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.TextView
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import io.livekit.android.LiveKit
import io.livekit.android.events.RoomEvent
import io.livekit.android.room.Room
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class VoiceCallActivity : AppCompatActivity() {

    private lateinit var room: Room
    private lateinit var statusView: TextView
    private lateinit var transcriptView: TextView
    private var micEnabled = false

    // Placeholders — your app already knows the logged-in driver and their current
    // order; these hardcoded values are only here to make this file runnable as-is.
    private val userId = "driver-test-1"
    private val orderId = "order-test-1"
    private val tokenServerUrl = "http://10.0.2.2:8080" // emulator loopback to host machine

    private val micPermissionLauncher =
        registerForActivityResult(ActivityResultContracts.RequestPermission()) { granted ->
            if (granted) {
                lifecycleScope.launch { connectToRoom() }
            } else {
                statusView.text = "Microphone permission denied — can't start the call."
            }
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_voice_call)

        statusView = findViewById(R.id.statusView)
        transcriptView = findViewById(R.id.transcriptView)
        findViewById<Button>(R.id.connectButton).setOnClickListener { requestMicAndConnect() }
        findViewById<Button>(R.id.muteButton).setOnClickListener { toggleMic() }
        findViewById<Button>(R.id.endCallButton).setOnClickListener { endCall() }

        room = LiveKit.create(applicationContext)

        lifecycleScope.launch {
            room.events.collect { event ->
                when (event) {
                    is RoomEvent.Connected -> statusView.text = "connected"
                    is RoomEvent.Disconnected -> statusView.text = "disconnected"
                    is RoomEvent.TrackSubscribed -> {
                        // audio auto-plays; nothing else to wire up for voice-only
                    }
                    is RoomEvent.TranscriptionReceived -> {
                        event.transcriptionSegments
                            .filter { it.final }
                            .forEach { segment -> transcriptView.append("\n${segment.text}") }
                    }
                    else -> {}
                }
            }
        }
    }

    private fun requestMicAndConnect() {
        val granted = ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) ==
            PackageManager.PERMISSION_GRANTED
        if (granted) {
            lifecycleScope.launch { connectToRoom() }
        } else {
            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private suspend fun connectToRoom() {
        statusView.text = "requesting token..."
        val (token, url) = fetchToken(userId, orderId)

        statusView.text = "connecting..."
        room.connect(url, token)

        room.localParticipant.setMicrophoneEnabled(true)
        micEnabled = true
        statusView.text = "connected — mic live"
    }

    private fun toggleMic() {
        lifecycleScope.launch {
            micEnabled = !micEnabled
            room.localParticipant.setMicrophoneEnabled(micEnabled)
        }
    }

    private fun endCall() {
        room.disconnect()
        statusView.text = "call ended"
    }

    /** Plain HttpURLConnection call to backend/token_server.py — no HTTP library assumed. */
    private suspend fun fetchToken(userId: String, orderId: String): Pair<String, String> =
        withContext(Dispatchers.IO) {
            val conn = URL("$tokenServerUrl/livekit-token").openConnection() as HttpURLConnection
            try {
                conn.requestMethod = "POST"
                conn.setRequestProperty("Content-Type", "application/json")
                conn.doOutput = true
                val body = JSONObject().put("user_id", userId).put("order_id", orderId).toString()
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }

                check(conn.responseCode == 200) { "token request failed: HTTP ${conn.responseCode}" }
                val responseJson = JSONObject(conn.inputStream.bufferedReader().readText())
                Pair(responseJson.getString("token"), responseJson.getString("url"))
            } finally {
                conn.disconnect()
            }
        }

    override fun onDestroy() {
        super.onDestroy()
        room.release()
    }
}
