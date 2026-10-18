package com.paralied.farplay;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import android.view.View;
import android.view.WindowManager;
import android.webkit.*;
import android.widget.EditText;
import com.google.zxing.integration.android.IntentIntegrator;
import com.google.zxing.integration.android.IntentResult;
import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.MessageDigest;
import java.security.cert.CertificateException;
import java.security.cert.X509Certificate;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import javax.net.ssl.*;
import okhttp3.*;
import okio.ByteString;
import org.json.*;

public class MainActivity extends Activity {
    private WebView web;
    private View custom;
    private WebChromeClient.CustomViewCallback customCallback;
    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final AtomicInteger generation = new AtomicInteger();
    private volatile WebSocket socket;
    private volatile OkHttpClient networkClient;
    private volatile boolean destroyed = false;
    private volatile boolean pairing = false;
    private JSONObject saved;
    private AlertDialog composer;
    private boolean playing=false;
    private static final String ORIGIN = "https://appassets.androidplatform.net";

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        try { saved = loadSaved(); } catch (Exception e) { saved = null; }
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(9,14,24));
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(false);
        web.getSettings().setDomStorageEnabled(false);
        web.getSettings().setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        web.getSettings().setMediaPlaybackRequiresUserGesture(false);
        web.addJavascriptInterface(new Bridge(), "FarPlay");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) { return true; }
            @Override public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                Uri u=req.getUrl();
                String p=u.getPath();
                if ("https".equals(u.getScheme()) && "appassets.androidplatform.net".equals(u.getHost()) &&
                    ("/index.html".equals(p) || "/client.js".equals(p) || "/style.css".equals(p))) {
                    try {
                        String mime=p.endsWith(".js")?"application/javascript":p.endsWith(".css")?"text/css":"text/html";
                        return new WebResourceResponse(mime,"UTF-8",getAssets().open(p.substring(1)));
                    } catch(IOException ignored) {}
                }
                return new WebResourceResponse("text/plain","UTF-8",new ByteArrayInputStream(new byte[0]));
            }
            @Override public void onPageFinished(WebView view,String url) { if ((ORIGIN+"/index.html").equals(url)) sendSaved(); }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onJsPrompt(WebView view,String url,String message,String defaultValue,JsPromptResult result) {
                if (!url.startsWith(ORIGIN+"/")) { result.cancel(); return true; }
                EditText input=new EditText(MainActivity.this); input.setSingleLine(true);
                new AlertDialog.Builder(MainActivity.this).setMessage(message).setView(input)
                    .setPositiveButton("Send",(d,w)->result.confirm(input.getText().toString()))
                    .setNegativeButton("Cancel",(d,w)->result.cancel()).setOnCancelListener(d->result.cancel()).show(); return true;
            }
            @Override public void onShowCustomView(View view,CustomViewCallback callback) {
                if(custom!=null){callback.onCustomViewHidden();return;}
                custom=view;customCallback=callback;setContentView(view);
                view.setSystemUiVisibility(View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY);
            }
            @Override public void onHideCustomView(){ hideFullscreen(); }
        });
        setContentView(web);
        web.loadUrl(ORIGIN+"/index.html");
    }

    private void hideFullscreen() {
        if(custom==null)return;
        custom=null;setContentView(web);
        if(customCallback!=null){customCallback.onCustomViewHidden();customCallback=null;}
    }
    private void emit(String type, Object data) {
        if(destroyed)return;
        String js="window.onNative&&window.onNative("+JSONObject.quote(type)+","+(data instanceof JSONObject ? data.toString() : JSONObject.quote(String.valueOf(data)))+")";
        runOnUiThread(()->{if(!destroyed&&web!=null)web.evaluateJavascript(js,null);});
    }
    private void error(String message) { emit("error",message); }
    private synchronized void sendSaved() {
        JSONObject info=new JSONObject();
        try { info.put("paired",saved!=null); info.put("name",saved==null?"My PC":saved.optString("name","My PC")); } catch(JSONException ignored){}
        emit("saved",info);
        try{emit("controls",new JSONObject(getPreferences(MODE_PRIVATE).getString("controls","{}")));}catch(JSONException ignored){}
    }
    private SecretKey storageKey() throws Exception {
        KeyStore ks=KeyStore.getInstance("AndroidKeyStore");ks.load(null);
        if(!ks.containsAlias("FarPlayPairing")){
            KeyGenerator gen=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            gen.init(new KeyGenParameterSpec.Builder("FarPlayPairing",KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());gen.generateKey();
        }
        return (SecretKey)ks.getKey("FarPlayPairing",null);
    }
    private JSONObject loadSaved() throws Exception {
        String raw=getPreferences(MODE_PRIVATE).getString("directPair",null);if(raw==null)return null;
        JSONObject box=new JSONObject(raw);
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");
        c.init(Cipher.DECRYPT_MODE,storageKey(),new GCMParameterSpec(128,Base64.decode(box.getString("iv"),Base64.NO_WRAP)));
        return new JSONObject(new String(c.doFinal(Base64.decode(box.getString("data"),Base64.NO_WRAP)),StandardCharsets.UTF_8));
    }
    private synchronized void save(JSONObject value) throws Exception {
        Cipher c=Cipher.getInstance("AES/GCM/NoPadding");c.init(Cipher.ENCRYPT_MODE,storageKey());
        JSONObject box=new JSONObject();box.put("iv",Base64.encodeToString(c.getIV(),Base64.NO_WRAP));
        box.put("data",Base64.encodeToString(c.doFinal(value.toString().getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));
        if(!getPreferences(MODE_PRIVATE).edit().putString("directPair",box.toString()).commit())throw new IOException("Could not save pairing");
        saved=value;
    }
    private static String fingerprint(X509Certificate cert) throws Exception {
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(cert.getEncoded());StringBuilder out=new StringBuilder();
        for(byte b:hash)out.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return out.toString();
    }
    private OkHttpClient client(final String pin) throws Exception {
        X509TrustManager trust=new X509TrustManager(){
            @Override public X509Certificate[] getAcceptedIssuers(){return new X509Certificate[0];}
            @Override public void checkClientTrusted(X509Certificate[] chain,String auth)throws CertificateException{throw new CertificateException("Client certificates not used");}
            @Override public void checkServerTrusted(X509Certificate[] chain,String auth)throws CertificateException{
                try {if(chain.length==0||!pin.equals(fingerprint(chain[0])))throw new CertificateException("PC identity mismatch");chain[0].checkValidity();}
                catch(CertificateException e){throw e;}catch(Exception e){throw new CertificateException(e);}
            }
        };
        SSLContext ssl=SSLContext.getInstance("TLS");ssl.init(null,new TrustManager[]{trust},null);
        return new OkHttpClient.Builder().sslSocketFactory(ssl.getSocketFactory(),trust)
            .hostnameVerifier((hostname,session)->{try{return pin.equals(fingerprint((X509Certificate)session.getPeerCertificates()[0]));}catch(Exception e){return false;}})
            .connectTimeout(3,TimeUnit.SECONDS).readTimeout(6,TimeUnit.SECONDS).writeTimeout(3,TimeUnit.SECONDS)
            .pingInterval(10,TimeUnit.SECONDS).followRedirects(false).followSslRedirects(false).retryOnConnectionFailure(false).build();
    }
    private JSONObject parseCode(String code)throws Exception{
        if(code==null||!code.startsWith("farplay:")||code.length()>4096)throw new Exception("Scan a FarPlay pairing QR code from your PC.");
        JSONObject p=new JSONObject(new String(Base64.decode(code.substring(8),Base64.URL_SAFE|Base64.NO_WRAP|Base64.NO_PADDING),StandardCharsets.UTF_8));
        if(p.getInt("v")!=2||!p.getString("pin").matches("[a-f0-9]{64}")||!p.getString("invite").matches("[A-Za-z0-9_-]{43}"))throw new Exception("Invalid pairing code.");
        JSONArray urls=p.getJSONArray("urls");if(urls.length()<1||urls.length()>2)throw new Exception("Invalid PC address.");
        for(int i=0;i<urls.length();i++){
            Uri u=Uri.parse(urls.getString(i));String host=u.getHost();
            if(!"https".equals(u.getScheme())||u.getPort()!=47990||host==null||!host.matches("[0-9]{1,3}(\\.[0-9]{1,3}){3}")||u.getUserInfo()!=null||u.getQuery()!=null||u.getFragment()!=null||!(u.getPath()==null||u.getPath().isEmpty()))throw new Exception("Invalid PC address.");
            for(String n:host.split("\\."))if(Integer.parseInt(n)>255)throw new Exception("Invalid PC address.");
        }
        return p;
    }
    private void pair(String code){
        if(pairing)return;pairing=true;
        io.execute(()->{
            OkHttpClient c=null;
            try{
                JSONObject p=parseCode(code);c=client(p.getString("pin"));JSONArray urls=p.getJSONArray("urls");
                JSONObject body=new JSONObject();body.put("invite",p.getString("invite"));body.put("name",android.os.Build.MODEL);
                Exception last=new IOException("PC unreachable");
                for(int i=0;i<urls.length();i++){
                    Request r=new Request.Builder().url(urls.getString(i)+"/pair").post(RequestBody.create(body.toString(),MediaType.get("application/json"))).build();
                    try(Response response=c.newCall(r).execute()){
                        if(!response.isSuccessful())throw new Exception("Pairing expired or rejected. Generate a new QR code on the PC.");
                        String token=new JSONObject(response.body().string()).getString("token");
                        if(!token.matches("[A-Za-z0-9_-]{43}"))throw new Exception("Invalid PC response.");
                        p.remove("invite");p.put("token",token);save(p);sendSaved();emit("paired","PC paired. Tap Connect.");return;
                    }catch(IOException e){last=e;}
                }
                throw new Exception("Cannot reach your PC. For first pairing, use your home Wi-Fi and allow FarPlay in Windows Firewall.",last);
            }catch(Exception e){error(e.getMessage());}
            finally{pairing=false;if(c!=null)c.connectionPool().evictAll();}
        });
    }
    private synchronized void disconnect(){
        generation.incrementAndGet();WebSocket old=socket;socket=null;
        if(old!=null){old.send("{\"type\":\"stop\"}");old.close(1000,"Phone stopped");old.cancel();}
        if(networkClient!=null){networkClient.dispatcher().cancelAll();networkClient.connectionPool().evictAll();networkClient=null;}
    }
    private void connect(){
        disconnect();final JSONObject p;
        synchronized(this){p=saved;}
        if(p==null){error("Pair your PC first.");return;}
        final int gen=generation.get();
        try { networkClient=client(p.getString("pin"));tryEndpoint(p,0,gen); }catch(Exception e){error("Saved pairing could not be loaded. Pair your PC again.");}
    }
    private void tryEndpoint(JSONObject p,int index,int gen){
        if(gen!=generation.get())return;
        try{
            JSONArray urls=p.getJSONArray("urls");
            if(index>=urls.length()){error("PC unreachable. Leave FarPlay open. If home Wi-Fi works but mobile data does not, open Network setup on the PC.");return;}
            Request r=new Request.Builder().url(urls.getString(index)+"/ws").header("Authorization","Bearer "+p.getString("token")).build();
            networkClient.newWebSocket(r,new WebSocketListener(){
                private boolean opened=false;
                @Override public void onOpen(WebSocket ws,Response response){
                    if(gen!=generation.get()){ws.cancel();return;}socket=ws;opened=true;
                }
                @Override public void onMessage(WebSocket ws,String text){
                    if(gen!=generation.get())return;
                    try{emit("message",new JSONObject(text));}catch(JSONException e){ws.cancel();error("Invalid PC response.");}
                }
                @Override public void onMessage(WebSocket ws,ByteString bytes){
                    if(gen!=generation.get()||bytes.size()<2||bytes.size()>2000000)return;
                    emit("packet",bytes.base64());
                }
                @Override public void onFailure(WebSocket ws,Throwable t,Response response){
                    if(gen!=generation.get())return;
                    if(!opened){
                        if(response!=null&&(response.code()==401||response.code()==409)){error(response.code()==401?"PC pairing was removed. Pair again.":"Another phone is connected.");return;}
                        tryEndpoint(p,index+1,gen);
                    }else{socket=null;error("Connection lost. Tap Connect to try again.");}
                }
                @Override public void onClosing(WebSocket ws,int code,String reason){ws.close(code,reason);if(gen==generation.get())emit("closed","PC disconnected. Tap Connect to try again.");}
                @Override public void onClosed(WebSocket ws,int code,String reason){if(gen==generation.get()){socket=null;emit("closed","PC disconnected. Tap Connect to try again.");}}
            });
        }catch(Exception e){error("Unable to connect. Pair your PC again.");}
    }
    private void showComposer(String kind,String draft){
        if(destroyed||!playing||composer!=null)return;
        final boolean chat="chat".equals(kind);
        EditText input=new EditText(this);
        input.setTextColor(Color.WHITE);input.setHintTextColor(Color.rgb(140,160,178));
        input.setTextSize(17);input.setSingleLine(true);
        input.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_FLAG_CAP_SENTENCES);
        input.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEND|android.view.inputmethod.EditorInfo.IME_FLAG_NO_EXTRACT_UI);
        input.setFilters(new android.text.InputFilter[]{new android.text.InputFilter.LengthFilter(200)});
        input.setHint(chat?"Message or /command":"Type into the selected PC field");
        input.setText(draft==null?"":draft);input.setSelection(input.length());
        android.widget.LinearLayout box=new android.widget.LinearLayout(this);box.setPadding(28,12,28,8);box.addView(input,new android.widget.LinearLayout.LayoutParams(-1,-2));
        final boolean[] completed={false};
        AlertDialog dialog=new AlertDialog.Builder(this,android.R.style.Theme_DeviceDefault_Dialog_Alert)
            .setTitle(chat?"Minecraft chat":"Type on your PC").setView(box)
            .setPositiveButton(chat?"Send":"Insert",null).setNegativeButton("Cancel",null)
            .setNeutralButton(chat?"/ Command":"Clear",null).create();
        composer=dialog;
        java.util.function.Consumer<Boolean> finish=cancel->{
            if(completed[0])return;completed[0]=true;
            JSONObject result=new JSONObject();try{result.put("text",input.getText().toString());}catch(JSONException ignored){}
            emit(cancel?"composer-cancel":"composer-send",result);dialog.dismiss();
        };
        dialog.setOnCancelListener(d->finish.accept(true));
        dialog.setOnDismissListener(d->{composer=null;if(playing)getWindow().getDecorView().setSystemUiVisibility(immersiveFlags());});
        dialog.setOnShowListener(d->{
            dialog.getButton(AlertDialog.BUTTON_POSITIVE).setOnClickListener(v->{if(input.length()>0)finish.accept(false);else input.setError("Type a message first");});
            dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setOnClickListener(v->finish.accept(true));
            dialog.getButton(AlertDialog.BUTTON_NEUTRAL).setOnClickListener(v->{input.setText(chat?"/":"");input.setSelection(input.length());});
            input.requestFocus();dialog.getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_VISIBLE|WindowManager.LayoutParams.SOFT_INPUT_ADJUST_RESIZE);
            input.postDelayed(()->{if(composer==dialog)((android.view.inputmethod.InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).showSoftInput(input,android.view.inputmethod.InputMethodManager.SHOW_IMPLICIT);},120);
        });
        input.setOnEditorActionListener((v,action,event)->{if(action==android.view.inputmethod.EditorInfo.IME_ACTION_SEND){if(input.length()>0)finish.accept(false);return true;}return false;});
        dialog.show();
    }
    private int immersiveFlags(){return View.SYSTEM_UI_FLAG_FULLSCREEN|View.SYSTEM_UI_FLAG_HIDE_NAVIGATION|View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY|View.SYSTEM_UI_FLAG_LAYOUT_STABLE|View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN|View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION;}
    private void setPlayMode(boolean enabled){
        if(playing==enabled)return;playing=enabled;
        if(!enabled&&composer!=null){composer.dismiss();composer=null;}
        if(android.os.Build.VERSION.SDK_INT>=28){
            WindowManager.LayoutParams params=getWindow().getAttributes();
            params.layoutInDisplayCutoutMode=enabled?WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES:WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_DEFAULT;
            getWindow().setAttributes(params);
        }
        setRequestedOrientation(enabled?android.content.pm.ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE:android.content.pm.ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED);
        getWindow().getDecorView().setSystemUiVisibility(enabled?immersiveFlags():View.SYSTEM_UI_FLAG_VISIBLE);
    }
    public class Bridge {
        @JavascriptInterface public void compose(String kind,String draft){runOnUiThread(()->showComposer(kind,draft));}
        @JavascriptInterface public void setPlaying(boolean enabled){runOnUiThread(()->setPlayMode(enabled));}
        @JavascriptInterface public void saveControls(String value){
            if(value==null||value.length()>512)return;
            try{
                JSONObject data=new JSONObject(value),clean=new JSONObject();
                clean.put("sensitivity",Math.max(.5,Math.min(4,data.optDouble("sensitivity",2))));
                clean.put("size",Math.max(80,Math.min(120,data.optInt("size",100))));
                clean.put("opacity",Math.max(30,Math.min(100,data.optInt("opacity",70))));
                clean.put("leftHanded",data.optBoolean("leftHanded",false));
                getPreferences(MODE_PRIVATE).edit().putString("controls",clean.toString()).apply();
            }catch(JSONException ignored){}
        }
        @JavascriptInterface public void scan(){runOnUiThread(()->new IntentIntegrator(MainActivity.this).setDesiredBarcodeFormats(IntentIntegrator.QR_CODE).setPrompt("Scan the code shown in FarPlay on your PC").setBeepEnabled(false).setOrientationLocked(false).initiateScan());}
        @JavascriptInterface public void pairCode(String code){pair(code);}
        @JavascriptInterface public void connectPC(){io.execute(()->connect());}
        @JavascriptInterface public void disconnectPC(){disconnect();}
        @JavascriptInterface public void signal(String text){WebSocket s=socket;if(s!=null&&text!=null&&text.length()<=65536&&s.queueSize()<65536)s.send(text);}
        @JavascriptInterface public void forget(){disconnect();synchronized(MainActivity.this){saved=null;getPreferences(MODE_PRIVATE).edit().remove("directPair").apply();}sendSaved();}
    }
    @Override protected void onActivityResult(int requestCode,int resultCode,Intent data){
        IntentResult result=IntentIntegrator.parseActivityResult(requestCode,resultCode,data);
        if(result!=null){if(result.getContents()!=null)pair(result.getContents());return;}
        super.onActivityResult(requestCode,resultCode,data);
    }
    @Override public void onBackPressed(){if(custom!=null){hideFullscreen();return;}if(playing)emit("back","");else super.onBackPressed();}
    @Override protected void onPause(){disconnect();if(web!=null)web.evaluateJavascript("end('Paused. Tap Connect to resume.')",null);super.onPause();}
    @Override protected void onDestroy(){destroyed=true;disconnect();io.shutdownNow();if(web!=null){web.removeJavascriptInterface("FarPlay");web.destroy();web=null;}super.onDestroy();}
}
