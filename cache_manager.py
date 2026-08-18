"""
中间产物缓存模块
缓存去重视频切片，避免每次运行都重新切片（约占总耗时40%）
缓存键：源文件路径+大小+修改时间 + 切片时长 + 分辨率 + 帧率
"""
import os
import json
import hashlib
import shutil

from config import config


class CacheManager:
    """中间产物缓存管理器"""

    def __init__(self):
        self.cache_dir = os.path.join(config.TEMP_DIR, "cache")
        self.index_file = os.path.join(self.cache_dir, "cache_index.json")
        os.makedirs(self.cache_dir, exist_ok=True)
        self._index = self._load_index()

    def _load_index(self) -> dict:
        """加载缓存索引"""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_index(self):
        """保存缓存索引"""
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(self._index, f, ensure_ascii=False, indent=2)

    def _make_cache_key(self, source_path: str, start_time: float, segment_duration: float,
                        resolution: str = "1080:1920", fps: int = 30) -> str:
        """
        生成缓存键
        包含：源文件路径+大小+修改时间 + 起始时间 + 切片时长 + 分辨率 + 帧率
        源文件变化时缓存自动失效
        """
        stat = os.stat(source_path)
        key_str = f"{os.path.abspath(source_path)}|{stat.st_size}|{stat.st_mtime}|{start_time}|{segment_duration}|{resolution}|{fps}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, source_path: str, start_time: float, segment_duration: float,
            resolution: str = "1080:1920", fps: int = 30) -> str:
        """
        获取缓存文件路径
        :return: 缓存文件路径（命中），None（未命中）
        """
        cache_key = self._make_cache_key(source_path, start_time, segment_duration, resolution, fps)
        if cache_key in self._index:
            cached_file = self._index[cache_key]
            if os.path.exists(cached_file):
                return cached_file
            else:
                # 缓存文件不存在了，删除索引
                del self._index[cache_key]
                self._save_index()
        return None

    def put(self, source_path: str, start_time: float, segment_duration: float, output_path: str,
            resolution: str = "1080:1920", fps: int = 30):
        """
        将切片文件存入缓存
        :param output_path: 刚生成的切片文件路径
        """
        cache_key = self._make_cache_key(source_path, start_time, segment_duration, resolution, fps)
        # 复制到缓存目录
        cache_filename = f"{cache_key}.mp4"
        cache_path = os.path.join(self.cache_dir, cache_filename)
        try:
            shutil.copy2(output_path, cache_path)
            self._index[cache_key] = cache_path
            self._save_index()
        except Exception as e:
            # 缓存失败不影响主流程
            print(f"缓存写入失败：{e}")

    def clear(self):
        """清空所有缓存"""
        if os.path.exists(self.cache_dir):
            shutil.rmtree(self.cache_dir)
        os.makedirs(self.cache_dir, exist_ok=True)
        self._index = {}
        self._save_index()
        print("缓存已清空")


# 全局单例
cache_manager = CacheManager()
