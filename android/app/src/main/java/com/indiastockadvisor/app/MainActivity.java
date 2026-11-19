package com.indiastockadvisor.app;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Bitmap;
import android.net.Uri;
import android.os.Bundle;
import android.os.Message;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private static final String GEMINI_PACKAGE = "com.google.android.apps.bard";
    private WebView web;

    /** True for links that belong to the Streamlit app itself. */
    private boolean isInternal(Uri u) {
        String host = u.getHost() == null ? "" : u.getHost();
        String appHost = Uri.parse(BuildConfig.APP_URL).getHost();
        return host.endsWith("streamlit.app") || host.endsWith("streamlit.io")
                || (appHost != null && host.equals(appHost));
    }

    /** Opens a link outside the app. Gemini links try the Gemini app first, then fall back to the browser. */
    private void openExternal(Uri u) {
        String host = u.getHost() == null ? "" : u.getHost();
        if (host.equals("gemini.google.com")) {
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, u).setPackage(GEMINI_PACKAGE));
                return;
            } catch (ActivityNotFoundException ignored) {
                // Gemini app not installed (or it doesn't handle this link): use the browser below.
            }
        }
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, u));
        } catch (Exception ignored) { }
    }

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        // Streamlit's "Open ..." buttons are <a target="_blank"> links. Without these two lines
        // the WebView silently drops them, which is why "Open Gemini" did nothing.
        s.setSupportMultipleWindows(true);
        s.setJavaScriptCanOpenWindowsAutomatically(true);

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                Uri u = request.getUrl();
                if (isInternal(u)) return false;
                openExternal(u);
                return true;
            }
        });

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {
                // A new-tab link was tapped: catch its address in a throw-away WebView and open it properly.
                final WebView popup = new WebView(MainActivity.this);
                popup.setWebViewClient(new WebViewClient() {
                    private boolean done = false;

                    private void route(WebView v, Uri u) {
                        if (done) return;
                        done = true;
                        if (isInternal(u)) web.loadUrl(u.toString()); else openExternal(u);
                        v.stopLoading();
                        v.post(v::destroy);
                    }

                    @Override
                    public boolean shouldOverrideUrlLoading(WebView v, WebResourceRequest request) {
                        route(v, request.getUrl());
                        return true;
                    }

                    @Override
                    public void onPageStarted(WebView v, String url, Bitmap favicon) {
                        if (url != null && !url.equals("about:blank")) route(v, Uri.parse(url));
                    }
                });
                WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                transport.setWebView(popup);
                resultMsg.sendToTarget();
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
