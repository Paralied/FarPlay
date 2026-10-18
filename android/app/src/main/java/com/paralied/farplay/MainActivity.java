package com.paralied.farplay;

import android.app.Activity;
import android.os.Bundle;
import android.graphics.Color;
import android.net.Uri;
import android.view.View;
import android.view.WindowManager;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebChromeClient;
import android.widget.*;

public class MainActivity extends Activity {
    private WebView web;
    private String origin;
    private View custom;
    private WebChromeClient.CustomViewCallback customCallback;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        showSetup();
    }
    private void showSetup() {
        if(web != null) { web.destroy(); web=null; }
        LinearLayout box=new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);box.setPadding(40,100,40,40);box.setBackgroundColor(Color.rgb(9,14,24));
        TextView title=new TextView(this);title.setText("FarPlay\nYour PC. Wherever you are.");title.setTextColor(Color.WHITE);title.setTextSize(27);box.addView(title);
        EditText url=new EditText(this);url.setTextColor(Color.WHITE);url.setHintTextColor(Color.GRAY);url.setSingleLine(true);url.setHint("https://your-service.example");
        url.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);
        url.setText(getPreferences(MODE_PRIVATE).getString("url", ""));box.addView(url);
        Button open=new Button(this);open.setText("Open my PC connection");box.addView(open);
        TextView note=new TextView(this);note.setText("Enter the HTTPS address of your deployed FarPlay service. Your phone pairing key is entered on the next screen.");note.setTextColor(Color.LTGRAY);box.addView(note);
        open.setOnClickListener(v->{
            String value=url.getText().toString().trim();
            Uri uri=Uri.parse(value);
            if(!"https".equals(uri.getScheme()) || uri.getHost()==null || uri.getUserInfo()!=null || uri.getQuery()!=null || uri.getFragment()!=null || (uri.getPath()!=null&&!uri.getPath().isEmpty()&&!"/".equals(uri.getPath()))) {
                Toast.makeText(this,"Enter an HTTPS service address without a path",Toast.LENGTH_LONG).show();return;
            }
            origin="https://"+uri.getAuthority();
            getPreferences(MODE_PRIVATE).edit().putString("url",origin).apply();openClient();
        });
        setContentView(box);
    }
    private void openClient() {
        web=new WebView(this);
        web.setBackgroundColor(Color.BLACK);
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(false);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setMixedContentMode(android.webkit.WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.getSettings().setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient(){
            @Override public boolean shouldOverrideUrlLoading(WebView view,WebResourceRequest request){
                Uri u=request.getUrl();return !origin.equals(u.getScheme()+"://"+u.getAuthority());
            }
        });
        web.setWebChromeClient(new WebChromeClient(){
            @Override public boolean onJsPrompt(WebView view,String url,String message,String defaultValue,android.webkit.JsPromptResult result){
                EditText input=new EditText(MainActivity.this);input.setSingleLine(true);
                new android.app.AlertDialog.Builder(MainActivity.this).setMessage(message).setView(input)
                  .setPositiveButton("Send",(dialog,which)->result.confirm(input.getText().toString()))
                  .setNegativeButton("Cancel",(dialog,which)->result.cancel()).setOnCancelListener(dialog->result.cancel()).show();return true;
            }
            @Override public void onShowCustomView(View view,CustomViewCallback callback){
                if(custom!=null){callback.onCustomViewHidden();return;}
                custom=view;customCallback=callback;setContentView(view);
                view.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
            }
            @Override public void onHideCustomView(){
                if(custom==null)return;custom=null;setContentView(web);customCallback.onCustomViewHidden();
            }
        });
        setContentView(web);web.loadUrl(origin+"/");
    }
    @Override public void onBackPressed(){
        if(custom!=null){custom=null;setContentView(web);customCallback.onCustomViewHidden();return;}
        if(web!=null){web.evaluateJavascript("end()",null);showSetup();}else super.onBackPressed();
    }
    @Override protected void onPause(){if(web!=null)web.evaluateJavascript("end('App paused. Reconnect to resume.')",null);super.onPause();}
    @Override protected void onDestroy(){if(web!=null)web.destroy();super.onDestroy();}
}
