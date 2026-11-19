package com.indiastockadvisor.app;

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {
    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);

        web.setWebViewClient(new WebViewClient());
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
