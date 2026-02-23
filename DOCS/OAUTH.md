# OAuth 认证集成

## 概述

fast-api 支持 Google 和 GitHub OAuth 登录，用户信息存储在 MySQL `users` 表。

## 配置

### 1. 环境变量

在 `.env` 中配置：

```env
# Google OAuth
GOOGLE_CLIENT_ID=your_google_client_id
GOOGLE_CLIENT_SECRET=your_google_client_secret

# GitHub OAuth
GITHUB_CLIENT_ID=your_github_client_id
GITHUB_CLIENT_SECRET=your_github_client_secret

# Session secret
SECRET_KEY=your_random_secret_key

# Frontend callback URL
FRONTEND_URL=http://localhost:3000
```

### 2. 获取 OAuth 凭证

**Google:**
1. 访问 https://console.cloud.google.com/
2. 创建项目 → APIs & Services → Credentials
3. 创建 OAuth 2.0 Client ID
4. 添加回调 URL: `http://localhost:14444/auth/callback/google`

**GitHub:**
1. 访问 https://github.com/settings/developers
2. New OAuth App
3. 添加回调 URL: `http://localhost:14444/auth/callback/github`

### 3. 数据库初始化

```bash
mysql -u root -p tts_bot < schema_users.sql
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/auth/login/google` | GET | 发起 Google 登录 |
| `/auth/login/github` | GET | 发起 GitHub 登录 |
| `/auth/callback/google` | GET | Google 回调（自动） |
| `/auth/callback/github` | GET | GitHub 回调（自动） |
| `/auth/me` | GET | 获取当前用户信息 |
| `/auth/logout` | POST | 登出 |

## 使用流程

### 前端登录

```javascript
// 重定向到 OAuth 登录
window.location.href = 'http://localhost:14444/auth/login/google';
// 或
window.location.href = 'http://localhost:14444/auth/login/github';
```

### 处理回调

OAuth 成功后重定向到：
```
{FRONTEND_URL}/auth/callback?token={session_token}
```

前端保存 token：
```javascript
const params = new URLSearchParams(window.location.search);
const token = params.get('token');
localStorage.setItem('auth_token', token);
```

### 使用 token

```javascript
fetch('http://localhost:14444/auth/me', {
  headers: {
    'Authorization': `Bearer ${token}`
  }
})
.then(r => r.json())
.then(user => console.log(user));
```

### 响应示例

```json
{
  "id": 1,
  "email": "user@example.com",
  "name": "John Doe",
  "avatar": "https://...",
  "provider": "google"
}
```

## 安全说明

- Session token 有效期 30 天
- 使用 `itsdangerous` 签名防篡改
- `SECRET_KEY` 必须保密且随机
- 生产环境使用 HTTPS
