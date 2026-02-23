"""OAuth authentication router"""
import os
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse
from authlib.integrations.starlette_client import OAuth
from itsdangerous import URLSafeTimedSerializer
import pymysql

router = APIRouter(prefix="/auth", tags=["auth"])

# OAuth config
oauth = OAuth()

oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
    client_kwargs={'scope': 'openid email profile'}
)

oauth.register(
    name='github',
    client_id=os.getenv('GITHUB_CLIENT_ID'),
    client_secret=os.getenv('GITHUB_CLIENT_SECRET'),
    authorize_url='https://github.com/login/oauth/authorize',
    authorize_params=None,
    access_token_url='https://github.com/login/oauth/access_token',
    access_token_params=None,
    client_kwargs={'scope': 'user:email'}
)

# Session serializer
serializer = URLSafeTimedSerializer(os.getenv('SECRET_KEY', 'dev-secret-key'))

def get_db():
    from main import db_pool
    return db_pool.connection()

@router.get("/login/{provider}")
async def login(provider: str, request: Request):
    """Initiate OAuth login"""
    if provider not in ['google', 'github']:
        raise HTTPException(400, "Invalid provider")
    
    redirect_uri = request.url_for('auth_callback', provider=provider)
    return await oauth.create_client(provider).authorize_redirect(request, redirect_uri)

@router.get("/callback/{provider}")
async def auth_callback(provider: str, request: Request):
    """OAuth callback"""
    if provider not in ['google', 'github']:
        raise HTTPException(400, "Invalid provider")
    
    client = oauth.create_client(provider)
    token = await client.authorize_access_token(request)
    
    # Get user info
    if provider == 'google':
        user_info = token.get('userinfo')
        email = user_info.get('email')
        name = user_info.get('name')
        avatar = user_info.get('picture')
    else:  # github
        resp = await client.get('https://api.github.com/user', token=token)
        user_data = resp.json()
        email = user_data.get('email')
        name = user_data.get('name') or user_data.get('login')
        avatar = user_data.get('avatar_url')
    
    if not email:
        raise HTTPException(400, "Email not provided")
    
    # Save/update user in database
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("""
                INSERT INTO users (email, name, avatar, provider, last_login)
                VALUES (%s, %s, %s, %s, NOW())
                ON DUPLICATE KEY UPDATE
                    name=%s, avatar=%s, last_login=NOW()
            """, (email, name, avatar, provider, name, avatar))
            conn.commit()
            
            c.execute("SELECT id, email, name, avatar FROM users WHERE email=%s", (email,))
            user = c.fetchone()
    finally:
        conn.close()
    
    # Generate session token
    session_token = serializer.dumps({'user_id': user['id'], 'email': email})
    
    # Redirect to frontend with token
    frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')
    return RedirectResponse(f"{frontend_url}/auth/callback?token={session_token}")

@router.get("/me")
async def get_current_user(request: Request):
    """Get current user info from session token or API token"""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        raise HTTPException(401, "Not authenticated")
    
    token = auth_header[7:]
    
    # Try session token first
    try:
        data = serializer.loads(token, max_age=86400*30)  # 30 days
        conn = get_db()
        try:
            with conn.cursor() as c:
                c.execute("SELECT id, email, name, avatar, provider FROM users WHERE id=%s", (data['user_id'],))
                user = c.fetchone()
                if user:
                    return user
        finally:
            conn.close()
    except:
        pass
    
    # Try API token
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("""
                SELECT u.id, u.email, u.name, u.avatar, u.provider 
                FROM users u
                JOIN user_tokens t ON u.id = t.user_id
                WHERE t.token = %s AND t.is_active = 1 
                AND (t.expires_at IS NULL OR t.expires_at > NOW())
            """, (token,))
            user = c.fetchone()
            if not user:
                raise HTTPException(401, "Invalid token")
            
            # Update last_used
            c.execute("UPDATE user_tokens SET last_used=NOW() WHERE token=%s", (token,))
            conn.commit()
            return user
    finally:
        conn.close()

@router.post("/token")
async def create_token(request: Request):
    """Create API token for current user"""
    user = await get_current_user(request)
    
    import secrets
    token = secrets.token_hex(32)
    
    data = await request.json()
    name = data.get('name', 'API Token')
    expires_days = data.get('expires_days')
    
    conn = get_db()
    try:
        with conn.cursor() as c:
            if expires_days:
                c.execute("""
                    INSERT INTO user_tokens (user_id, token, name, expires_at)
                    VALUES (%s, %s, %s, DATE_ADD(NOW(), INTERVAL %s DAY))
                """, (user['id'], token, name, expires_days))
            else:
                c.execute("""
                    INSERT INTO user_tokens (user_id, token, name)
                    VALUES (%s, %s, %s)
                """, (user['id'], token, name))
            conn.commit()
            return {"token": token, "name": name}
    finally:
        conn.close()

@router.get("/tokens")
async def list_tokens(request: Request):
    """List all tokens for current user"""
    user = await get_current_user(request)
    
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("""
                SELECT id, name, created_at, last_used, expires_at, is_active
                FROM user_tokens WHERE user_id=%s ORDER BY created_at DESC
            """, (user['id'],))
            return {"tokens": c.fetchall()}
    finally:
        conn.close()

@router.delete("/tokens/{token_id}")
async def delete_token(token_id: int, request: Request):
    """Delete a token"""
    user = await get_current_user(request)
    
    conn = get_db()
    try:
        with conn.cursor() as c:
            c.execute("DELETE FROM user_tokens WHERE id=%s AND user_id=%s", (token_id, user['id']))
            conn.commit()
            return {"success": True}
    finally:
        conn.close()

@router.post("/logout")
async def logout():
    """Logout (client should delete token)"""
    return {"success": True, "message": "Logged out"}
