#include <ESP8266WiFi.h>
#include <ESP8266WebServer.h>
#include <WiFiManager.h> // https://github.com/tzapu/WiFiManager

// Определяем пин для импульса (D1 на платах NodeMCU/Wemos соответствует GPIO 5)
#define PULSE_PIN 5 

ESP8266WebServer server(80);

// HTML-страница с кнопкой
const char* htmlPage = R"rawliteral(
<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Управление реле</title>
  <style>
    body { font-family: Arial, sans-serif; text-align: center; margin-top: 20vh; background-color: #f4f4f9; }
    .btn { 
      background-color: #008CBA; 
      color: white; 
      padding: 20px 40px; 
      font-size: 24px; 
      border: none; 
      border-radius: 8px; 
      cursor: pointer; 
      box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .btn:active { background-color: #005f7a; transform: translateY(2px); }
  </style>
</head>
<body>
  <h1>Управление дверью</h1>
  <form action="/pulse" method="POST">
    <button class="btn" type="submit">Открыть дверь</button>
  </form>
</body>
</html>
)rawliteral";

// Обработчик главной страницы
void handleRoot() {
  server.send(200, "text/html", htmlPage);
}

// Обработчик нажатия кнопки
void handlePulse() {
  // Включаем выход
  digitalWrite(PULSE_PIN, HIGH);
  
  // Ждем 2 секунды (2000 миллисекунд)
  delay(2000);
  
  // Выключаем выход
  digitalWrite(PULSE_PIN, LOW);
  
  // Перенаправляем пользователя обратно на главную страницу, чтобы избежать повторной отправки формы
  server.sendHeader("Location", "/");
  server.send(303);
}

void setup() {
  Serial.begin(115200);
  
  // Настройка пина
  pinMode(PULSE_PIN, OUTPUT);
  digitalWrite(PULSE_PIN, LOW); // По умолчанию выключен

  // Инициализация WiFiManager
  WiFiManager wifiManager;

  //wifiManager.resetSettings();
  
  // Устанавливаем таймаут для портала настроек (в секундах). 
  // Если за 3 минуты (180 сек) никто не введет настройки, ESP перезагрузится
  wifiManager.setConfigPortalTimeout(90);

  Serial.println("Подключение к WiFi...");
  
  // Создаем точку доступа с именем "ESP8266_Setup" без пароля.
  // Если WiFi сохранен, он подключится к нему. Если нет - откроет эту точку.
  if (!wifiManager.autoConnect("ESP8266_Setup")) {
    Serial.println("Не удалось подключиться к WiFi и время ожидания истекло.");
    delay(3000);
    // Перезагрузка для повторной попытки
    ESP.restart();
  }

  // Если код дошел сюда, значит мы подключены к роутеру
  Serial.println("Подключено к WiFi!");
  Serial.print("IP адрес для управления: ");
  Serial.println(WiFi.localIP());

  // Настройка маршрутов веб-сервера
  server.on("/", HTTP_GET, handleRoot);
  server.on("/pulse", HTTP_POST, handlePulse);

  // Запуск сервера
  server.begin();
}

void loop() {
  // Обработка входящих клиентских запросов
  server.handleClient();
}