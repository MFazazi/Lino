package com.fazasolutions.lino.mobile

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.media.MediaRecorder
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.BufferedReader
import java.io.DataOutputStream
import java.io.File
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

private val LINO_CORE_URL = BuildConfig.LINO_CORE_URL
private const val MIN_RECORDING_DURATION_MS = 700L

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { LinoMobileApp() } }
    }
}

class LinoRecorder(private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var recordingStartedAt = 0L
    private val audioFile = File(context.cacheDir, "lino_voice.m4a")

    @Suppress("DEPRECATION")
    private fun createMediaRecorder(): MediaRecorder =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(context)
        else MediaRecorder()

    fun start(): Boolean = try {
        if (audioFile.exists()) audioFile.delete()
        recorder = createMediaRecorder().apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setAudioSamplingRate(44100)
            setAudioEncodingBitRate(128000)
            setOutputFile(audioFile.absolutePath)
            prepare()
            start()
        }
        recordingStartedAt = System.currentTimeMillis()
        true
    } catch (e: Exception) {
        e.printStackTrace()
        try { recorder?.release() } catch (_: Exception) {}
        recorder = null
        false
    }

    fun stop(): File? {
        val duration = System.currentTimeMillis() - recordingStartedAt
        try {
            recorder?.stop()
        } catch (e: Exception) {
            e.printStackTrace()
            try { recorder?.release() } catch (_: Exception) {}
            recorder = null
            if (audioFile.exists()) audioFile.delete()
            return null
        }
        try { recorder?.release() } catch (_: Exception) {}
        recorder = null

        if (duration < MIN_RECORDING_DURATION_MS) {
            if (audioFile.exists()) audioFile.delete()
            return null
        }

        return if (audioFile.exists() && audioFile.length() > 1000) audioFile else null
    }
}

@Composable
fun LinoMobileApp() {
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val recorder = remember { LinoRecorder(context) }

    var connected by remember { mutableStateOf(false) }
    var recording by remember { mutableStateOf(false) }
    var processing by remember { mutableStateOf(false) }
    var status by remember { mutableStateOf("Prêt") }

    val currentConnected = rememberUpdatedState(connected)
    val currentProcessing = rememberUpdatedState(processing)

    val microphonePermissionLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> status = if (granted) "Prêt" else "Microphone refusé" }

    LaunchedEffect(Unit) {
        while (isActive) {
            connected = checkLinoCore()
            if (!connected) status = "PC hors ligne"
            else if (!recording && !processing && status == "PC hors ligne") status = "Prêt"
            delay(3000)
        }
    }

    Box(
        modifier = Modifier.fillMaxSize().background(Color(0xFF0E1420)),
        contentAlignment = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.Center,
            modifier = Modifier.padding(24.dp),
        ) {
            LinoMobileFace(recording, processing)
            Spacer(Modifier.height(24.dp))
            Text("LINO", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.SemiBold)
            Spacer(Modifier.height(10.dp))
            Text(
                if (connected) "● PC connecté" else "● PC hors ligne",
                color = if (connected) Color(0xFF7DDFA5) else Color(0xFFFF7C7C),
                fontSize = 15.sp,
            )
            Spacer(Modifier.height(42.dp))

            Box(
                modifier = Modifier
                    .size(200.dp)
                    .background(
                        when {
                            recording -> Color(0xFF536DE8)
                            processing -> Color(0xFF35466C)
                            else -> Color(0xFF1B2638)
                        },
                        CircleShape,
                    )
                    .pointerInput(Unit) {
                        detectTapGestures(
                            onPress = {
                                if (currentProcessing.value) return@detectTapGestures
                                if (!currentConnected.value) {
                                    status = "PC hors ligne"
                                    return@detectTapGestures
                                }

                                val granted = ContextCompat.checkSelfPermission(
                                    context,
                                    Manifest.permission.RECORD_AUDIO,
                                ) == PackageManager.PERMISSION_GRANTED

                                if (!granted) {
                                    microphonePermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                    return@detectTapGestures
                                }

                                setLinoState("listening")
                                if (!recorder.start()) {
                                    status = "Erreur microphone"
                                    setLinoState("idle")
                                    return@detectTapGestures
                                }

                                recording = true
                                status = "J'écoute..."
                                tryAwaitRelease()
                                recording = false

                                val audio = recorder.stop()
                                if (audio == null) {
                                    status = "Enregistrement trop court"
                                    setLinoState("idle")
                                    return@detectTapGestures
                                }

                                setLinoState("transcribing")
                                processing = true
                                status = "Envoyé au PC"

                                scope.launch {
                                    try {
                                        uploadAudio(audio)
                                        status = "Prêt"
                                    } catch (e: Exception) {
                                        e.printStackTrace()
                                        status = "Erreur de connexion"
                                        setLinoState("idle")
                                    } finally {
                                        processing = false
                                    }
                                }
                            }
                        )
                    },
                contentAlignment = Alignment.Center,
            ) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        when {
                            recording -> "J'écoute"
                            processing -> "Envoi"
                            else -> "Maintenir"
                        },
                        color = Color.White,
                        fontSize = 22.sp,
                        fontWeight = FontWeight.SemiBold,
                    )
                    Spacer(Modifier.height(6.dp))
                    Text(
                        when {
                            recording -> "Relâche quand tu as fini"
                            processing -> "Lino travaille sur le PC"
                            else -> "pour parler à Lino"
                        },
                        color = Color.White.copy(alpha = 0.60f),
                        fontSize = 13.sp,
                    )
                }
            }

            Spacer(Modifier.height(26.dp))
            Text(status, color = Color(0xFF9AA8BF), fontSize = 14.sp)
        }
    }
}

@Composable
fun LinoMobileFace(listening: Boolean, processing: Boolean) {
    Box(
        modifier = Modifier.size(100.dp).background(
            when {
                listening -> Color(0xFF7894FF)
                processing -> Color(0xFF8498D8)
                else -> Color(0xFF9FB5FF)
            },
            CircleShape,
        ),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            when {
                listening -> "• ◡ •"
                processing -> "• _ •"
                else -> "• ᴗ •"
            },
            color = Color(0xFF172039),
            fontSize = 30.sp,
        )
    }
}

suspend fun checkLinoCore(): Boolean = withContext(Dispatchers.IO) {
    try {
        val connection = URL("$LINO_CORE_URL/health").openConnection() as HttpURLConnection
        connection.requestMethod = "GET"
        connection.connectTimeout = 1500
        connection.readTimeout = 1500
        connection.connect()
        val ok = connection.responseCode == HttpURLConnection.HTTP_OK
        connection.disconnect()
        ok
    } catch (_: Exception) {
        false
    }
}

suspend fun setLinoState(state: String) = withContext(Dispatchers.IO) {
    try {
        val connection = URL("$LINO_CORE_URL/state/$state").openConnection() as HttpURLConnection
        connection.requestMethod = "POST"
        connection.connectTimeout = 2000
        connection.readTimeout = 2000
        connection.connect()
        connection.responseCode
        connection.disconnect()
    } catch (e: Exception) {
        e.printStackTrace()
    }
}

suspend fun uploadAudio(file: File) = withContext(Dispatchers.IO) {
    val boundary = "Lino-${UUID.randomUUID()}"
    val connection = URL("$LINO_CORE_URL/transcribe").openConnection() as HttpURLConnection
    connection.requestMethod = "POST"
    connection.doOutput = true
    connection.connectTimeout = 10000
    connection.readTimeout = 120000
    connection.setRequestProperty("Content-Type", "multipart/form-data; boundary=$boundary")

    DataOutputStream(connection.outputStream).use { output ->
        output.writeBytes("--$boundary\r\n")
        output.writeBytes("Content-Disposition: form-data; name=\"file\"; filename=\"lino_voice.m4a\"\r\n")
        output.writeBytes("Content-Type: audio/mp4\r\n\r\n")
        file.inputStream().use { input ->
            val buffer = ByteArray(8192)
            var read: Int
            while (input.read(buffer).also { read = it } != -1) {
                output.write(buffer, 0, read)
            }
        }
        output.writeBytes("\r\n--$boundary--\r\n")
        output.flush()
    }

    val code = connection.responseCode
    val stream = if (code in 200..299) connection.inputStream else connection.errorStream
    if (stream != null) {
        BufferedReader(InputStreamReader(stream)).use { it.readText() }
    }
    connection.disconnect()
    if (code !in 200..299) throw Exception("Lino Core HTTP $code")
}
