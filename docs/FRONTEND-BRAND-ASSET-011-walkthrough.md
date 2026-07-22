# Walkthrough

Klasöre eklenen logonun en güncel ve daha hafif sürümü, `frontend/public/med-agent-logo.svg` olarak kalıcı asset adına taşındı. Uygulamadaki tüm logo yüzeyleri zaten merkezî `MedAgentLogo` bileşenini kullandığı için bileşenin içeriği yeni assetle değiştirilerek marka tek noktadan güncellendi.

Giriş ve splash ekranındaki giriş hareketi, küçük avatarlar ve geniş logo yüzeylerindeki sakin hareket SVG dosyasının dış kapsayıcısında uygulanır. Hareket azaltma tercihi desteklenmeye devam eder.

Tarayıcı favicon'u da aynı SVG assetine bağlıdır; alternatif eski logo referansı bulunmaz.
