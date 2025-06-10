
---

**Цель:** Развернуть на сервере полностью готовый к работе сервер Matrix (Synapse) из вашего форка, с базой данных PostgreSQL, веб-интерфейсом для администрирования Synapse-Admin (также из вашего форка) и кастомным модулем `role_management`. Все компоненты будут работать в Docker-контейнерах, а Nginx будет выступать в качестве реверс-прокси с HTTPS (SSL от Let's Encrypt).

**Используемые компоненты:**
*   **Synapse:** `uriymartynenko/synapse:v1.130.0`
*   **Synapse Admin:** `uriymartynenko/synapse-admin:v0.11.1`
*   **База данных:** `postgres:14-alpine`
*   **Реверс-прокси:** `nginx:alpine`
*   **Домен:** `matrixdev.ru` (используйте вместо него свой домен)
*   **Модуль:** `role_management`

---

### **Шаг I: Подготовка сервера и DNS**

1.  **Сервер:** Подключитесь по SSH к вашему Linux-серверу (инструкция ориентирована на Ubuntu/Debian) с правами `sudo`.

2.  **DNS-настройка:** Убедитесь, что **A-запись** (и/или AAAA для IPv6) для домена `matrixdev.ru` указывает на публичный IP-адрес вашего сервера.

3.  **Установка зависимостей:** Установите все необходимые пакеты, включая Docker и Certbot.
    ```bash
    # 1. Обновляем список пакетов и систему
    sudo apt-get update && sudo apt-get upgrade -y

    # 2. Устанавливаем пакеты, необходимые для добавления репозитория Docker
    sudo apt-get install -y apt-transport-https ca-certificates curl software-properties-common

    # 3. Добавляем официальный GPG-ключ Docker
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

    # 4. Добавляем репозиторий Docker
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

    # 5. Снова обновляем список пакетов, чтобы включить репозиторий Docker
    sudo apt-get update

    # 6. Устанавливаем Docker, Docker Compose и Certbot
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin certbot python3-certbot-nginx

    # 7. (Рекомендуется) Добавляем вашего пользователя в группу docker
    sudo usermod -aG docker $USER
    ```
    **ВАЖНО:** После добавления пользователя в группу `docker`, **необходимо переподключиться к SSH-сессии**, чтобы изменения вступили в силу. В противном случае, вам придется использовать `sudo` для всех команд `docker`.

### **Шаг II: Создание структуры проекта**

1.  Создайте корневую папку для проекта и перейдите в нее.
    ```bash
    mkdir matrix-server && cd matrix-server
    ```
2.  Создайте все необходимые поддиректории для данных и конфигураций.
    ```bash
    mkdir -p synapse-data synapse-admin-config
    ```
3.  **Добавьте код модуля:** Склонируйте исходный код вашего модуля `role_management` из папки `matrix-server` командой:
    ```bash
    git clone https://gitlab.com/uriy.martynenko/modules.git
    ```
и переименуйте папку `modules` в папку `synapse-modules`. Структура должна быть такой, чтобы Python мог его найти:

    ```
    matrix-server/
    └── synapse-modules/
        └── role_management/
            ├── __init__.py
            ├── module.py   # Файл с классом RoleModule
            └── ...         # другие файлы модуля
    ```
    *Этот шаг критически важен, иначе Synapse не найдет модуль при запуске.*

### **Шаг III: Конфигурация компонентов**

На этом этапе мы создадим все необходимые конфигурационные файлы.

#### **1. Генерация конфигурации Synapse**

Запустите одноразовый Docker-контейнер для генерации файла `homeserver.yaml` и ключа подписи.
```bash
docker run --rm -it \
  -v ./synapse-data:/data \
  --env SYNAPSE_SERVER_NAME=matrixdev.ru \
  --env SYNAPSE_REPORT_STATS=no \
  uriymartynenko/synapse:v1.130.0 generate
```
В папке `synapse-data` появятся файлы `homeserver.yaml` и `matrixdev.ru.signing.key`.

#### **2. Редактирование конфигурации Synapse (`homeserver.yaml`)**

1.  Откройте сгенерированный файл `synapse-data/homeserver.yaml` для редактирования.
    ```bash
    nano synapse-data/homeserver.yaml
    ```
2.  Найдите и **измените/раскомментируйте** следующие секции. Если секции нет, добавьте ее.

    ```yaml
    # Убедитесь, что server_name правильный
    server_name: "matrixdev.ru"

    # PID-файл
    pid_file: /data/homeserver.pid

    # Настройки листенера для работы за реверс-прокси
    listeners:
      - port: 8008
        tls: false
        type: http
        x_forwarded: true
        bind_addresses: ['0.0.0.0']
        resources:
          - names: [client, federation]
            compress: false

    # Подключение к базе данных PostgreSQL
    database:
      name: psycopg2
      args:
        user: postgres
        password: postgres-password # Этот пароль будет в docker-compose.yml
        database: synapse
        host: db # Имя сервиса postgres в docker-compose
        cp_min: 5
        cp_max: 10

    # Путь к медиа-хранилищу
    media_store_path: /data/media_store

    # Включение Admin API для работы Synapse-Admin
    admin_api_enabled: true

    # Подключение вашего кастомного модуля
    modules:
      - module: role_management.module.RoleModule
        config:
            enable_api: true
            # Здесь можно добавить другие параметры конфигурации модуля

    # Настройка регистрации пользователей
    # Для первого запуска и создания админа можно включить:
    enable_registration: true
    enable_registration_without_verification: true
    # После создания админа рекомендуется установить: enable_registration: false
    ```
3.  Сохраните и закройте файл (`Ctrl+O`, `Enter`, `Ctrl+X`).

#### **3. Создание конфигурации Synapse-Admin (`config.json`)**

1.  Создайте файл конфигурации для веб-интерфейса админки.
    ```bash
    nano synapse-admin-config/config.json
    ```
2.  Вставьте в него следующий JSON:
    ```json
    {
      "homeserver": "https://matrixdev.ru",
      "api": {
        "v1": "/_synapse/admin/v1",
        "v2": "/_synapse/admin/v2"
      }
    }
    ```
3.  Сохраните и закройте файл.

#### **4. Создание конфигурации Nginx (`nginx.conf`)**

1.  Создайте основной файл конфигурации для Nginx.
    ```bash
    nano nginx.conf
    ```
2.  Вставьте в него следующую конфигурацию:
    ```nginx
    # Блок для HTTP -> HTTPS редиректа и проверки Certbot
    server {
        listen 80;
        listen [::]:80;
        server_name matrixdev.ru;

        location ~ /.well-known/acme-challenge/ {
            allow all;
            root /var/www/html;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # Основной блок для HTTPS
    server {
        listen 443 ssl http2;
        listen [::]:443 ssl http2;
        server_name matrixdev.ru;

        # Пути к SSL-сертификатам. Certbot создаст их автоматически.
        ssl_certificate /etc/letsencrypt/live/matrixdev.ru/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/matrixdev.ru/privkey.pem;
        include /etc/letsencrypt/options-ssl-nginx.conf;
        ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

        client_max_body_size 128M;

        # Для федерации и обнаружения клиента
        location /.well-known/matrix/server {
            return 200 '{"m.server": "matrixdev.ru:443"}';
            add_header Content-Type application/json;
            add_header "Access-Control-Allow-Origin" *;
        }
        location /.well-known/matrix/client {
            return 200 '{"m.homeserver": {"base_url": "https://matrixdev.ru"}, "m.identity_server": {"base_url": "https://vector.im"}}';
            add_header Content-Type application/json;
            add_header "Access-Control-Allow-Origin" *;
        }

        # Проксирование для Synapse Admin UI
        location /synapse-admin/ {
            proxy_pass http://synapse-admin:80/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
        }

        # Проксирование для Matrix API
        location ~ ^(/_matrix|/_synapse) {
            proxy_pass http://synapse:8008;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header Host $host;
            proxy_http_version 1.1;
            proxy_set_header Connection "";
            proxy_read_timeout 86400s;
            proxy_send_timeout 86400s;
        }
    }
    ```
3.  Сохраните и закройте файл.

#### **5. Создание файла `docker-compose.yml`**

1.  Создайте главный файл `docker-compose.yml`, который свяжет все сервисы вместе.
    ```bash
    nano docker-compose.yml
    ```
2.  Вставьте в него следующее содержимое:
    ```yaml
    version: '3.8'

    services:
      db:
        image: postgres:14-alpine
        container_name: matrix_postgres
        environment:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres-password
          POSTGRES_DB: synapse
          POSTGRES_INITDB_ARGS: "--encoding='UTF8' --lc-collate='C' --lc-ctype='C'"
        volumes:
          - postgres-data:/var/lib/postgresql/data
        networks:
          - matrix-net
        restart: unless-stopped

      synapse:
        image: uriymartynenko/synapse:v1.130.0
        container_name: matrix_synapse
        volumes:
          - ./synapse-data:/data
          - ./synapse-modules:/app/modules
        environment:
          PYTHONPATH: /app/modules:${PYTHONPATH:-}
        depends_on:
          - db
        networks:
          - matrix-net
        restart: unless-stopped

      nginx:
        image: nginx:alpine
        container_name: matrix_nginx
        ports:
          - "80:80"
          - "443:443"
        volumes:
          - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
          - /etc/letsencrypt:/etc/letsencrypt:ro
          - /var/www/html:/var/www/html:ro
        depends_on:
          - synapse
          - synapse-admin
        networks:
          - matrix-net
        restart: unless-stopped

      synapse-admin:
        image: uriymartynenko/synapse-admin:v0.11.1
        container_name: synapse-admin
        volumes:
          - ./synapse-admin-config/config.json:/usr/share/nginx/html/config/config.json:ro
        networks:
          - matrix-net
        restart: unless-stopped

    volumes:
      postgres-data:

    networks:
      matrix-net:
    ```
3.  Сохраните и закройте файл.

### **Шаг IV: Запуск и финальная настройка**

1.  **Получение SSL-сертификата:**
    *   Создайте директорию для веб-рута Certbot.
      ```bash
      sudo mkdir -p /var/www/html
      ```
    *   Запустите только Nginx, чтобы Certbot мог с ним работать.
      ```bash
      docker compose up -d nginx
      ```
    *   Запустите Certbot для получения сертификата.
      ```bash
      sudo certbot --nginx -d matrixdev.ru --email your-email@example.com --agree-tos --no-eff-email
      ```
      Когда Certbot спросит, делать ли редирект с HTTP на HTTPS, выберите опцию **2 (Redirect)**.

2.  **Запуск всего стека:**
    Теперь, когда все конфигурации готовы и сертификаты получены, запускаем все сервисы.
    ```bash
      docker compose up -d
    ```

3.  **Проверка статуса:**
    Убедитесь, что все 4 контейнера запущены и работают.
    ```bash
    docker compose ps
    ```
    Все сервисы должны иметь статус `Up` или `running`.

4.  **Создание первого пользователя (Администратора):**
    Создайте первого пользователя с правами администратора через командную строку.
    ```bash
    docker compose exec synapse register_new_matrix_user http://localhost:8008 -u ваш_логин -p 'ваш_супер_сложный_пароль' -a
    ```
    *   Замените `ваш_логин` и `ваш_супер_сложный_пароль`.
    *   Ваш полный Matrix ID будет `@ваш_логин:matrixdev.ru`.

### **Шаг V: Проверка работоспособности**

1.  **Клиент Matrix:** Откройте любой клиент (например, [Element Web](https://app.element.io/)), при входе выберите "Изменить" сервер и введите `https://matrixdev.ru`. Войдите, используя созданные учетные данные.

2.  **Synapse Admin:** Откройте в браузере адрес **`https://matrixdev.ru/synapse-admin/`**. Войдите, используя ваш полный Matrix ID (`@ваш_логин:matrixdev.ru`) и пароль.

3.  **Федерация:** Проверьте ваш сервер на [Matrix Federation Tester](https://federationtester.matrix.org/), введя домен `matrixdev.ru`.

Поздравляю! Ваш Matrix-сервер полностью настроен и готов к работе.