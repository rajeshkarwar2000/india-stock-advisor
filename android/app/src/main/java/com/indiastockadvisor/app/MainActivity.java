package com.indiastockadvisor.app;

import android.app.Activity;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private static final String GEMINI_PACKAGE = "com.google.android.apps.bard";
    private WebView web;

    /** Called from the web page as Android.copy(text) and Android.openGemini(). */
    private class Bridge {
        @JavascriptInterface
        public void copy(String text) {
            ClipboardManager cm = (ClipboardManager) getSystemService(Context.CLIPBOARD_SERVICE);
            if (cm != null) cm.setPrimaryClip(ClipData.newPlainText("prompt", text));
        }

        @JavascriptInterface
        public void openGemini() {
            runOnUiThread(() -> {
                try {
                    Intent i = new Intent(Intent.ACTION_MAIN);
                    i.addCategory(Intent.CATEGORY_LAUNCHER);
                    i.setPackage(GEMINI_PACKAGE);
                    i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    startActivity(i);
                } catch (Exception notInstalled) {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse("https://gemini.google.com/app")));
                    } catch (Exception ignored) { }
                }
            });
        }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);

        web.addJavascriptInterface(new Bridge(), "Android");
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                String host = u.getHost() == null ? "" : u.getHost();
                String appHost = Uri.parse(BuildConfig.APP_URL).getHost();
                boolean internal = host.endsWith("streamlit.app") || host.endsWith("streamlit.io")
                        || (appHost != null && host.equals(appHost));
                if (internal) return false;
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, u));
                } catch (Exception ignored) { }
                return true;
            }
        });
        web.setDownloadListener((url, userAgent, contentDisposition, mime, length) ->
                startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))));

        String url = BuildConfig.APP_URL;
        if (url == null || url.isEmpty()) {
            web.loadData("<h2>App address not set</h2>"
                    + "<p>In GitHub, add a repository variable named APP_URL with your "
                    + "Streamlit app link, then re-run the workflow to rebuild this app.</p>",
                    "text/html", "UTF-8");
        } else {
            web.loadUrl(url);
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
