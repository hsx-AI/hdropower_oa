"""Create accounts without putting passwords in shell arguments or source."""
import argparse
import getpass
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import User, engine_from_env, initialize
from .auth import hash_password

def main():
    parser = argparse.ArgumentParser(description='初始化平台管理员（已有同名用户时拒绝覆盖）')
    parser.add_argument('--file', type=Path, help='私密管理员初始化 JSON 文件')
    args = parser.parse_args()
    if args.file:
        account = json.loads(args.file.read_text(encoding='utf-8'))
        username, password = account['username'], account['password']
    else:
        username = input('管理员账号 [admin]: ').strip() or 'admin'
        password = getpass.getpass('管理员密码（至少12位）: ')
        if password != getpass.getpass('再次输入密码: '):
            parser.error('两次密码不一致')
    if not isinstance(username, str) or not username.strip() or len(username) > 64 or not isinstance(password, str) or not 12 <= len(password) <= 256:
        parser.error('账号不能为空且不超过64位，密码为12至256位')
    engine = engine_from_env()
    try:
        initialize(engine)
        with Session(engine) as db:
            if db.scalar(select(User).where(User.username == username.strip())):
                parser.error('账号已存在，未更改原账号')
            db.add(User(username=username.strip(), display_name='系统管理员', role='admin',
                        password_hash=hash_password(password), department='水电分厂'))
            db.commit()
        print('管理员已创建。')
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
