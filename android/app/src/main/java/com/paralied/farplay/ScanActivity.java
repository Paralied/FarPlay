package com.paralied.farplay;

import android.Manifest;
import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.widget.Toast;
import com.google.zxing.BarcodeFormat;
import com.journeyapps.barcodescanner.BarcodeCallback;
import com.journeyapps.barcodescanner.BarcodeResult;
import com.journeyapps.barcodescanner.DecoratedBarcodeView;
import com.journeyapps.barcodescanner.DefaultDecoderFactory;
import java.util.Collections;

/** Explicit in-app camera: no external scanner or browser intents. */
public class ScanActivity extends Activity {
    private DecoratedBarcodeView scanner;
    private boolean finished=false;
    @Override public void onCreate(Bundle state){
        super.onCreate(state);
        scanner=new DecoratedBarcodeView(this);
        scanner.setStatusText("Point at the pairing QR code in FarPlay on your PC");
        scanner.getBarcodeView().setDecoderFactory(new DefaultDecoderFactory(Collections.singletonList(BarcodeFormat.QR_CODE)));
        setContentView(scanner);
        scanner.getBarcodeView().addStateListener(new com.journeyapps.barcodescanner.CameraPreview.StateListener(){
            public void previewSized(){} public void previewStarted(){} public void previewStopped(){} public void cameraClosed(){}
            public void cameraError(Exception e){
                if(!finished){finished=true;Toast.makeText(ScanActivity.this,"Camera unavailable. Close other camera apps or paste the PC pairing code.",Toast.LENGTH_LONG).show();finish();}
            }
        });
        scanner.decodeSingle(new BarcodeCallback(){
            @Override public void barcodeResult(BarcodeResult result){
                if(finished)return;
                String code=result.getText();
                if(code==null||!code.startsWith("farplay:")){
                    Toast.makeText(ScanActivity.this,"Use the pairing QR code shown by FarPlay on your PC.",Toast.LENGTH_LONG).show();
                    scanner.decodeSingle(this);return;
                }
                finished=true;scanner.pause();
                setResult(RESULT_OK,new Intent().putExtra("pairCode",code));finish();
            }
        });
        if(checkSelfPermission(Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.CAMERA},10);
    }
    private void resumeCamera(){
        if(!finished&&checkSelfPermission(Manifest.permission.CAMERA)==PackageManager.PERMISSION_GRANTED){
            try{scanner.resume();}catch(RuntimeException e){Toast.makeText(this,"Camera unavailable. You can paste the PC pairing code instead.",Toast.LENGTH_LONG).show();finish();}
        }
    }
    @Override protected void onResume(){super.onResume();resumeCamera();}
    @Override protected void onPause(){if(scanner!=null)scanner.pause();super.onPause();}
    @Override public void onRequestPermissionsResult(int requestCode,String[] permissions,int[] results){
        super.onRequestPermissionsResult(requestCode,permissions,results);
        if(requestCode==10){
            if(results.length>0&&results[0]==PackageManager.PERMISSION_GRANTED)resumeCamera();
            else{Toast.makeText(this,"Camera permission is needed to scan. You can still paste the PC pairing code.",Toast.LENGTH_LONG).show();finish();}
        }
    }
}
