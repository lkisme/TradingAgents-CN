# 向量模型配置简化设计 (v2.2 - 最小改动)

## 1. 设计思路

**核心逻辑**：从 MongoDB `llm_providers` 中查找支持 `embedding` 的 provider → 有就用，没有就禁用。

**改动范围**（最小化）：
1. DashScope 批量调用
2. 异常处理
3. 维度检测（避免切换模型时崩溃）

**不改动**：
- MongoDB 字段（无新增）
- Provider 查询逻辑（保持原有 find_one）

## 2. 实现方案

### 2.1 初始化逻辑改造（加入维度检测）

```python
class FinancialSituationMemory:
    def __init__(self, name, config):
        self.config = config
        
        # 从 MongoDB 查找支持 embedding 的 provider
        self.embedding_provider = self._find_embedding_provider()
        
        if self.embedding_provider:
            self.client = self._init_embedding_client()
            self.embedding_model = self.embedding_provider.get("embedding_model", "text-embedding-v3")
            self.model_dimension = self._get_model_dimension()
            
            # 初始化 ChromaDB
            self.chroma_manager = ChromaDBManager()
            self.situation_collection = self.chroma_manager.get_or_create_collection(name)
            
            # 🆕 维度检测
            if not self._check_dimension_compatibility():
                self.client = "DISABLED"
                logger.warning(f"⚠️ 记忆功能已禁用（维度不匹配）")
            else:
                logger.info(f"✅ 使用 {self.embedding_provider['name']} embedding 服务 (维度={self.model_dimension})")
        else:
            self.client = "DISABLED"
            logger.warning(f"⚠️ 无可用 embedding provider，记忆功能禁用")
    
    def _get_model_dimension(self) -> int:
        """获取 embedding 模型维度"""
        dim_map = {
            "text-embedding-v3": 1024,
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
            "bge-large-zh": 1024,
            "bge-base-zh": 768,
        }
        return dim_map.get(self.embedding_model, 1024)
    
    def _check_dimension_compatibility(self) -> bool:
        """检查维度兼容性"""
        try:
            # 查询集合现有向量（peek 不需要 embedding）
            existing = self.situation_collection.peek(limit=1)
            
            if existing and existing['embeddings'] and len(existing['embeddings']) > 0:
                existing_dim = len(existing['embeddings'][0])
                
                if self.model_dimension != existing_dim:
                    logger.warning(f"⚠️ 维度不匹配: 模型={self.model_dimension}, 集合={existing_dim}")
                    logger.warning(f"💡 解决方案: 1) 重建集合(丢失历史记忆) 2) 切换到{existing_dim}维模型")
                    return False
            
            return True
        except Exception as e:
            # 新集合无数据或异常，跳过检查
            logger.debug(f"📊 维度检查跳过: {e}")
            return True
```

### 2.2 embedding 调用逻辑改造（批量 + 异常处理）

```python
def _get_embeddings(self, texts: List[str]) -> List[List[float]]:
    """获取向量（批量调用 + 异常处理）"""
    if self.client == "DISABLED":
        raise Exception("Embedding 功能已禁用")
    
    provider_name = self.embedding_provider["name"]
    
    try:
        if provider_name == "dashscope":
            return self._get_dashscope_embeddings(texts)
        else:
            return self._get_openai_embeddings(texts)
    except Exception as e:
        logger.error(f"❌ Embedding 调用失败 ({provider_name}): {e}")
        raise

def _get_dashscope_embeddings(self, texts: List[str]) -> List[List[float]]:
    """阿里百炼 embedding（批量调用）"""
    import dashscope
    from dashscope import TextEmbedding
    
    # 🆕 批量调用，DashScope 支持最多 25 条
    batch_size = 25
    all_embeddings = []
    
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        response = TextEmbedding.call(
            model=self.embedding_model,
            input=batch  # 批量传入
        )
        
        if response.status_code == 200:
            batch_embeddings = [item['embedding'] for item in response.output['embeddings']]
            all_embeddings.extend(batch_embeddings)
        else:
            raise Exception(f"DashScope embedding failed: {response.message}")
    
    return all_embeddings

def _get_openai_embeddings(self, texts: List[str]) -> List[List[float]]:
    """OpenAI 兼容 embedding（批量调用）"""
    response = self.client.embeddings.create(
        model=self.embedding_model,
        input=texts
    )
    return [item.embedding for item in response.data]
```

### 2.3 调用方异常处理

```python
def add_situations(self, situations_and_recommendations):
    """添加记忆"""
    try:
        # ... 原有逻辑 ...
        embeddings = self._get_embeddings([sit for sit, rec in situations_and_recommendations])
        # ... 后续处理 ...
    except Exception as e:
        logger.error(f"❌ 添加记忆失败: {e}")
        return  # 跳过，不崩溃

def get_memories(self, current_situation: str, n_matches: int = 5) -> list:
    """查询记忆"""
    try:
        # ... 原有逻辑 ...
        embeddings = self._get_embeddings([current_situation])
        # ... 后续处理 ...
    except Exception as e:
        logger.error(f"❌ 查询记忆失败: {e}")
        return []  # 返回空列表，不影响后续流程
```

## 3. 改动范围

| 文件 | 改动 |
|------|------|
| `memory.py` | `__init__` 加入维度检测 |
| | `_get_model_dimension` 新增方法 |
| | `_check_dimension_compatibility` 新增方法 |
| | `_get_dashscope_embeddings` 改为批量调用 |
| | `_get_embeddings` 加 try/except |
| | `add_situations` 加异常处理 |
| | `get_memories` 加异常处理 |

## 4. 维度不匹配时的用户操作

日志输出：
```
⚠️ 维度不匹配: 模型=1536, 集合=1024
💡 解决方案: 1) 重建集合(丢失历史记忆) 2) 切换到1024维模型
```

用户可选：
- **重建集合**：删除旧集合，重新创建（丢失历史记忆）
- **切换模型**：换回原来维度的模型

## 5. 实施步骤

1. 添加 `_get_model_dimension` 方法
2. 添加 `_check_dimension_compatibility` 方法
3. 在 `__init__` 中调用维度检测
4. `_get_dashscope_embeddings` 改为批量调用
5. `_get_embeddings` 加异常处理
6. `add_situations` 和 `get_memories` 加异常处理

**预估时间**：1.5 小时

---

**状态**：包含维度检测，最小改动
