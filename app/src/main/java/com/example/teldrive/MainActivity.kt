package com.example.teldrive

import android.app.Activity
import android.content.Intent
import android.graphics.Bitmap
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.webkit.ConsoleMessage
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout

class MainActivity : AppCompatActivity() {

    companion object {
        private const val TARGET_URL = "https://teldrive-loht.onrender.com"
        private const val MAX_RETRIES = 3
    }

    private lateinit var webView: WebView
    private var swipeRefreshLayout: SwipeRefreshLayout? = null
    private var filePathCallback: ValueCallback<Array<Uri>>? = null

    private var retryCount = 0
    private val mainHandler = Handler(Looper.getMainLooper())
    private var retryRunnable: Runnable? = null

    private val fileChooserLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (filePathCallback == null) return@registerForActivityResult
        val results: Array<Uri>? = if (result.resultCode == Activity.RESULT_OK) {
            val intent = result.data
            if (intent?.data != null) {
                arrayOf(intent.data!!)
            } else if (intent?.clipData != null) {
                val count = intent.clipData!!.itemCount
                Array(count) { i -> intent.clipData!!.getItemAt(i).uri }
            } else {
                null
            }
        } else {
            null
        }
        filePathCallback?.onReceiveValue(results)
        filePathCallback = null
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        swipeRefreshLayout = findViewById(R.id.swipeRefreshLayout)
        webView = findViewById(R.id.webView)

        setupWebViewSettings()
        setupWebViewClients()
        setupSwipeRefresh()
        setupBackNavigation()

        Log.d("TelDriveWebView", "Loading URL: $TARGET_URL")
        webView.loadUrl(TARGET_URL)
    }

    @Suppress("DEPRECATION")
    private fun setupWebViewSettings() {
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            databaseEnabled = true
            loadWithOverviewMode = true
            useWideViewPort = true
            allowContentAccess = true
            allowFileAccess = true
            mixedContentMode = WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
            javaScriptCanOpenWindowsAutomatically = true
        }
    }

    private fun setupWebViewClients() {
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(
                view: WebView?,
                request: WebResourceRequest?
            ): Boolean {
                return false
            }

            override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                super.onPageStarted(view, url, favicon)
                Log.d("TelDriveWebView", "Page started: $url")
            }

            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                Log.d("TelDriveWebView", "Page finished: $url")
                swipeRefreshLayout?.isRefreshing = false
                retryCount = 0
            }

            override fun onReceivedError(
                view: WebView?,
                request: WebResourceRequest?,
                error: WebResourceError?
            ) {
                super.onReceivedError(view, request, error)
                if (request?.isForMainFrame == true) {
                    val errorCode = error?.errorCode ?: 0
                    val desc = error?.description?.toString() ?: "Unknown error"
                    Log.e("TelDriveWebView", "Main frame error ($errorCode): $desc")

                    val isNetworkOrTimeoutError = errorCode == ERROR_HOST_LOOKUP ||
                            errorCode == ERROR_CONNECT ||
                            errorCode == ERROR_TIMEOUT ||
                            errorCode == ERROR_UNKNOWN

                    if (isNetworkOrTimeoutError && retryCount < MAX_RETRIES) {
                        retryCount++
                        Toast.makeText(
                            this@MainActivity,
                            "Starting cloud server, please wait... (Retry $retryCount/$MAX_RETRIES)",
                            Toast.LENGTH_LONG
                        ).show()

                        retryRunnable?.let { mainHandler.removeCallbacks(it) }
                        retryRunnable = Runnable {
                            Log.d("TelDriveWebView", "Retrying loadUrl ($retryCount/$MAX_RETRIES): $TARGET_URL")
                            webView.loadUrl(TARGET_URL)
                        }
                        mainHandler.postDelayed(retryRunnable!!, 5000)
                    } else if (retryCount >= MAX_RETRIES) {
                        Toast.makeText(
                            this@MainActivity,
                            "Could not connect to cloud server: $desc",
                            Toast.LENGTH_LONG
                        ).show()
                    }
                }
            }
        }

        webView.webChromeClient = object : WebChromeClient() {
            override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                Log.d("TelDriveConsole", "${consoleMessage?.message()} -- Line ${consoleMessage?.lineNumber()} of ${consoleMessage?.sourceId()}")
                return super.onConsoleMessage(consoleMessage)
            }

            override fun onShowFileChooser(
                webView: WebView?,
                filePathCallback: ValueCallback<Array<Uri>>?,
                fileChooserParams: FileChooserParams?
            ): Boolean {
                this@MainActivity.filePathCallback?.onReceiveValue(null)
                this@MainActivity.filePathCallback = filePathCallback

                val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE)
                    type = "*/*"
                    putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
                }

                return try {
                    fileChooserLauncher.launch(Intent.createChooser(intent, "Select File"))
                    true
                } catch (e: Exception) {
                    this@MainActivity.filePathCallback = null
                    false
                }
            }
        }
    }

    private fun setupSwipeRefresh() {
        swipeRefreshLayout?.setOnRefreshListener {
            retryCount = 0
            webView.reload()
        }

        swipeRefreshLayout?.setOnChildScrollUpCallback { _, _ ->
            webView.scrollY > 0
        }
    }

    private fun setupBackNavigation() {
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (webView.canGoBack()) {
                    webView.goBack()
                } else {
                    isEnabled = false
                    onBackPressedDispatcher.onBackPressed()
                }
            }
        })
    }

    override fun onDestroy() {
        retryRunnable?.let { mainHandler.removeCallbacks(it) }
        super.onDestroy()
    }
}
