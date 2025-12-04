"""
子域名词库工具函数
"""
import random
import re
from typing import Optional, List
from .models import SubdomainWord


def get_available_subdomain_with_number(base_word: str, exclude_words: Optional[List[str]] = None, 
                                       use_dash: bool = False) -> str:
    """
    为给定的基础词找到一个可用的子域名（如果已被使用，则添加数字后缀）
    
    Args:
        base_word: 基础词（例如: 'www'）
        exclude_words: 要排除的词列表（例如已使用的子域名）
        use_dash: 是否使用短横线分隔（www-0）还是直接拼接（www0）
    
    Returns:
        可用的子域名（例如: 'www', 'www0', 'www-0', 'www1' 等）
    """
    exclude_words = exclude_words or []
    separator = '-' if use_dash else ''
    
    # 首先检查基础词是否可用
    if base_word not in exclude_words:
        return base_word
    
    # 如果基础词已被使用，尝试添加数字后缀（0-9）
    for num in range(10):  # 0-9
        candidate = f"{base_word}{separator}{num}"
        if candidate not in exclude_words:
            return candidate
    
    # 如果 0-9 都被使用，继续尝试更大的数字
    counter = 10
    while True:
        candidate = f"{base_word}{separator}{counter}"
        if candidate not in exclude_words:
            return candidate
        counter += 1
        # 防止无限循环（虽然不太可能）
        if counter > 999:
            break
    
    # 如果还是找不到，返回带数字的版本
    return f"{base_word}{separator}99"


def get_random_subdomain_word(exclude_words: Optional[List[str]] = None, 
                              use_dash: bool = False) -> Optional[str]:
    """
    从词库中随机选择一个启用的子域名词，如果已被使用则自动添加数字后缀
    
    Args:
        exclude_words: 要排除的词列表（例如已使用的子域名）
        use_dash: 是否使用短横线分隔（www-0）还是直接拼接（www0）
    
    Returns:
        随机选择的子域名词（如果原词已被使用，则返回带数字的版本）
    """
    exclude_words = exclude_words or []
    
    # 获取所有启用的词
    words = SubdomainWord.objects.filter(is_active=True).values_list('word', flat=True)
    
    if not words:
        return None
    
    # 随机打乱顺序，尝试找到可用的词
    words_list = list(words)
    random.shuffle(words_list)
    
    for word in words_list:
        # 尝试获取可用的子域名（如果已被使用，会自动添加数字）
        available_subdomain = get_available_subdomain_with_number(word, exclude_words, use_dash)
        
        # 如果返回的是基础词本身，说明可用
        if available_subdomain == word:
            # 更新使用次数
            try:
                word_obj = SubdomainWord.objects.get(word=word)
                word_obj.usage_count += 1
                word_obj.save(update_fields=['usage_count'])
            except SubdomainWord.DoesNotExist:
                pass
            return word
        else:
            # 如果返回的是带数字的版本，说明基础词已被使用，但找到了可用版本
            # 也更新基础词的使用次数（因为它是"被尝试使用"的）
            try:
                word_obj = SubdomainWord.objects.get(word=word)
                word_obj.usage_count += 1
                word_obj.save(update_fields=['usage_count'])
            except SubdomainWord.DoesNotExist:
                pass
            return available_subdomain
    
    # 如果所有词都被使用且无法添加数字，返回 None
    return None


def get_subdomain_with_fallback(exclude_words: Optional[List[str]] = None, 
                                 fallback_prefix: str = 'node',
                                 use_dash: bool = False) -> str:
    """
    获取子域名词，如果词库中没有可用词，则使用带数字的后备方案
    
    Args:
        exclude_words: 要排除的词列表
        fallback_prefix: 后备前缀（当没有可用词时使用）
        use_dash: 是否使用短横线分隔（node-0）还是直接拼接（node0）
    
    Returns:
        子域名（不包含域名后缀）
    """
    # 首先尝试从词库中获取
    word = get_random_subdomain_word(exclude_words, use_dash)
    
    if word:
        return word
    
    # 如果没有可用词，使用后备方案：prefix + 数字
    return get_available_subdomain_with_number(fallback_prefix, exclude_words, use_dash)


def get_all_active_words() -> List[str]:
    """获取所有启用的子域名词列表"""
    return list(SubdomainWord.objects.filter(is_active=True).values_list('word', flat=True))
