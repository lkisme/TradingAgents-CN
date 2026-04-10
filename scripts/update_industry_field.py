#!/usr/bin/env python3
"""
批量更新 stock_basic_info 集合的 industry 字段
从 akshare 获取个股行业信息并更新到 MongoDB
"""

import asyncio
import sys
import os
from datetime import datetime

# 添加项目根目录到路径
project_root = os.path.abspath(os.path.dirname(__file__))
sys.path.insert(0, project_root)

try:
    import akshare as ak
except ImportError:
    print("❌ akshare 未安装")
    sys.exit(1)

try:
    from pymongo import MongoClient
except ImportError:
    print("❌ pymongo 未安装")
    sys.exit(1)


def get_mongodb_connection():
    """获取 MongoDB 连接"""
    # 从环境变量读取配置
    mongodb_host = os.getenv('MONGODB_HOST', 'localhost')
    mongodb_port = int(os.getenv('MONGODB_PORT', 27017))
    mongodb_username = os.getenv('MONGODB_USERNAME', 'admin')
    mongodb_password = os.getenv('MONGODB_PASSWORD', 'tradingagents123')
    mongodb_database = os.getenv('MONGODB_DATABASE', 'tradingagents')
    mongodb_auth_source = os.getenv('MONGODB_AUTH_SOURCE', 'admin')

    connection_string = f"mongodb://{mongodb_username}:{mongodb_password}@{mongodb_host}:{mongodb_port}/{mongodb_auth_source}"

    client = MongoClient(connection_string, serverSelectionTimeoutMS=5000)
    db = client[mongodb_database]

    # 测试连接
    try:
        client.admin.command('ping')
        print(f"✅ MongoDB 连接成功: {mongodb_host}")
        return db
    except Exception as e:
        print(f"❌ MongoDB 连接失败: {e}")
        return None


def get_stock_industry_from_akshare(stock_code: str) -> str:
    """
    从 akshare 获取单只股票的行业信息
    
    Args:
        stock_code: 6位股票代码
        
    Returns:
        行业名称，如果获取失败返回空字符串
    """
    try:
        df = ak.stock_individual_info_em(symbol=stock_code)
        # 找到行业行
        industry_row = df[df['item'] == '行业']
        if not industry_row.empty:
            industry = industry_row.iloc[0]['value']
            # 清理行业名称（去掉后面的级别符号如 'Ⅱ', 'Ⅲ'）
            # 例如 '银行Ⅱ' -> '银行'
            industry_clean = industry.rstrip('ⅡⅢⅣⅤⅥⅦⅧⅨⅩ').strip()
            return industry_clean
        return ""
    except Exception as e:
        print(f"⚠️ 获取 {stock_code} 行业失败: {e}")
        return ""


def update_industry_fields():
    """
    批量更新 stock_basic_info 集合的 industry 字段
    """
    db = get_mongodb_connection()
    if db is None:
        return
    
    collection = db["stock_basic_info"]
    
    # 查询所有 industry 为空的数据
    query = {
        "source": "akshare",
        "$or": [
            {"industry": ""},
            {"industry": None},
            {"industry": {"$exists": False}}
        ]
    }
    
    total = collection.count_documents(query)
    print(f"📊 需要更新的股票数量: {total}")
    
    if total == 0:
        print("✅ 所有股票的行业信息已存在，无需更新")
        return
    
    # 分批处理
    batch_size = 50
    updated_count = 0
    failed_count = 0
    
    cursor = collection.find(query).batch_size(batch_size)
    
    for doc in cursor:
        stock_code = doc.get('code')
        stock_name = doc.get('name', '')
        
        if not stock_code:
            continue
        
        print(f"🔍 正在获取 {stock_code} ({stock_name}) 的行业信息...")
        
        # 获取行业信息
        industry = get_stock_industry_from_akshare(stock_code)
        
        if industry:
            # 更新数据库
            result = collection.update_one(
                {"code": stock_code, "source": "akshare"},
                {"$set": {"industry": industry, "industry_updated_at": datetime.now()}}
            )
            
            if result.modified_count > 0:
                updated_count += 1
                print(f"  ✅ 更新成功: {stock_code} -> {industry}")
            else:
                failed_count += 1
                print(f"  ⚠️ 更新失败: {stock_code}")
        else:
            failed_count += 1
            print(f"  ❌ 未获取到行业信息: {stock_code}")
        
        # 每处理100条打印进度
        if (updated_count + failed_count) % 100 == 0:
            print(f"\n📈 进度: 已处理 {updated_count + failed_count}/{total}, 成功 {updated_count}, 失败 {failed_count}\n")
    
    print(f"\n{'=' * 60}")
    print(f"✅ 更新完成")
    print(f"   成功: {updated_count}")
    print(f"   失败: {failed_count}")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    print("=" * 60)
    print("批量更新 stock_basic_info 集合的 industry 字段")
    print("=" * 60)
    
    update_industry_fields()