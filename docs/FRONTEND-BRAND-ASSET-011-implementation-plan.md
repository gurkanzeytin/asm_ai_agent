# Implementation Plan

## Amaç

Kullanıcının sağladığı SVG dosyasını uygulamadaki tüm logo yüzeylerinin tek kaynağı yapmak.

## Uygulama

- SVG dosyasını web uyumlu `med-agent-logo.svg` adına taşı.
- Merkezî `MedAgentLogo` bileşenini bu asseti gösterecek şekilde güncelle.
- Splash ve giriş animasyonlarını SVG dış kapsayıcısında koru.
- Sidebar, sohbet başlığı, ajan avatarı ve boş ekranı aynı bileşenden besle.
- Favicon bağlantısını aynı SVG dosyasına yönlendir.
- Asset sözleşmesini test et.
