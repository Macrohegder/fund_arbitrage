#!/usr/bin/env python3
"""
行情数据管理器 - IB专用版（仅使用IB数据源）
==============================
仅使用 Interactive Brokers 数据源，无降级机制

Features:
- 仅IB实时数据
- 盘后数据快照
- 交易时段智能判断
- A股开盘参考价（基于IB盘后数据）

Usage:
    from quote_manager import QuoteManager, TradingHours
    
    # 初始化
    qm = QuoteManager(auto_connect=True)
    
    # 获取行情
    quote = qm.get_quote("XOP")
    if quote:
        print(f"XOP: {quote.price}, 时段: {quote.session}")
    else:
        print("IB数据获取失败，不交易")
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path
import threading
import pytz

# 导入IB客户端
try:
    from ib_realtime_client import IBRealtimeClient, TickData, TradingHours, TradingSession
    HAS_IB = True
except ImportError:
    HAS_IB = False
    print("❌ IB模块未找到，系统无法运行")


@dataclass
class Quote:
    """统一行情数据结构"""
    symbol: str
    price: float
    change_pct: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "unknown"  # 仅 ib_realtime, ib_after_hours
    latency_ms: float = 0.0
    bid: Optional[float] = None
    ask: Optional[float] = None
    volume: Optional[int] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    session: str = "unknown"
    is_realtime: bool = False
    is_extended_hours: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "price": self.price,
            "change_pct": self.change_pct,
            "timestamp": self.timestamp.isoformat(),
            "source": self.source,
            "latency_ms": self.latency_ms,
            "bid": self.bid,
            "ask": self.ask,
            "volume": self.volume,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "session": self.session,
            "is_realtime": self.is_realtime,
            "is_extended_hours": self.is_extended_hours,
        }


class QuoteManager:
    """
    行情数据管理器 - IB专用版
    仅使用IB数据源，失败则返回None，不做降级
    """
    
    def __init__(
        self,
        auto_connect: bool = True,
        ib_host: str = "127.0.0.1",
        ib_port: int = 4002,
        ib_client_id: int = 11
    ):
        self.ib_host = ib_host
        self.ib_port = ib_port
        self.ib_client_id = ib_client_id
        
        # IB客户端
        self.ib_client: Optional[IBRealtimeClient] = None
        self._ib_connected = False
        
        # 缓存
        self._cache: Dict[str, Quote] = {}
        self._after_hours_cache: Dict[str, Quote] = {}
        self._cache_lock = threading.Lock()
        
        # 统计数据
        self._stats = {
            "requests": 0,
            "ib_hits": 0,
            "ib_after_hours_hits": 0,
            "errors": 0,
        }
        
        # 自动连接IB
        if auto_connect and HAS_IB:
            self._connect_ib()
    
    def _connect_ib(self) -> bool:
        """尝试连接IB"""
        if not HAS_IB:
            print("❌ IB模块未找到")
            return False
            
        try:
            print(f"🔌 正在连接 IB Gateway {self.ib_host}:{self.ib_port}...")
            self.ib_client = IBRealtimeClient(
                host=self.ib_host,
                port=self.ib_port,
                client_id=self.ib_client_id
            )
            
            if self.ib_client.connect():
                self._ib_connected = True
                
                # 启动IB数据处理线程
                self._start_ib_processor()
                
                print("✅ IB 连接成功")
                return True
            else:
                print("❌ IB 连接失败")
                return False
                
        except Exception as e:
            print(f"❌ IB 连接异常: {e}")
            self._ib_connected = False
            return False
    
    def _start_ib_processor(self):
        """启动IB数据处理线程"""
        def processor():
            while self._ib_connected:
                try:
                    tick = self.ib_client.get_tick(timeout=1)
                    if tick and tick.last:
                        quote = Quote(
                            symbol=tick.symbol,
                            price=tick.last,
                            change_pct=tick.change_pct or 0,
                            timestamp=tick.timestamp,
                            source="ib_realtime",
                            bid=tick.bid,
                            ask=tick.ask,
                            volume=tick.volume,
                            high=tick.high,
                            low=tick.low,
                            close=tick.close,
                            session=tick.session,
                            is_realtime=True,
                            is_extended_hours=tick.session in ["pre_market", "after_hours"]
                        )
                        with self._cache_lock:
                            self._cache[tick.symbol] = quote
                            
                            # 如果是盘后数据，单独保存
                            if tick.session == "after_hours":
                                self._after_hours_cache[tick.symbol] = quote
                                
                except Exception as e:
                    pass
        
        thread = threading.Thread(target=processor, daemon=True)
        thread.start()
    
    def subscribe(self, symbol: str) -> bool:
        """订阅指定symbol（包含盘后数据）"""
        if self._ib_connected and self.ib_client:
            return self.ib_client.subscribe(symbol, include_extended=True)
        return False
    
    def get_quote(
        self,
        symbol: str,
        prefer_realtime: bool = True,
        max_age: Optional[int] = None
    ) -> Optional[Quote]:
        """
        获取指定symbol的行情 - 仅使用IB数据源
        
        Args:
            symbol: 股票代码
            prefer_realtime: 是否优先获取实时数据
            max_age: 最大允许数据年龄(秒)
            
        Returns:
            Quote 对象或 None（IB失败时返回None，不做降级）
        """
        self._stats["requests"] += 1
        
        # 获取当前交易时段
        current_session = TradingHours.get_session()
        
        # 1. 检查缓存中的IB实时数据
        with self._cache_lock:
            cached = self._cache.get(symbol)
        
        if cached:
            # 根据当前时段判断数据有效性
            if current_session == TradingSession.CLOSED:
                # 休市时，盘后数据1小时内有效
                if cached.is_extended_hours:
                    age = (datetime.now() - cached.timestamp).total_seconds()
                    if age < 3600:
                        self._stats["ib_after_hours_hits"] += 1
                        return cached
            else:
                # 交易时段，数据在有效期内
                age = (datetime.now() - cached.timestamp).total_seconds()
                validity = max_age if max_age else 5
                if age < validity:
                    self._stats["ib_hits"] += 1
                    return cached
        
        # 2. 尝试从IB获取实时数据
        if prefer_realtime and self._ib_connected:
            ib_quote = self._fetch_from_ib(symbol)
            if ib_quote:
                with self._cache_lock:
                    self._cache[symbol] = ib_quote
                self._stats["ib_hits"] += 1
                return ib_quote
        
        # 3. 休市时尝试获取盘后快照
        if current_session == TradingSession.CLOSED:
            ah_quote = self.get_after_hours_reference(symbol)
            if ah_quote:
                self._stats["ib_after_hours_hits"] += 1
                return ah_quote
        
        # IB获取失败，返回None（不做降级）
        self._stats["errors"] += 1
        return None
    
    def get_after_hours_reference(self, symbol: str) -> Optional[Quote]:
        """
        获取盘后收盘参考价 - 仅使用IB数据源
        """
        # 1. 检查内存缓存
        with self._cache_lock:
            ah_cached = self._after_hours_cache.get(symbol)
        
        if ah_cached:
            age = (datetime.now() - ah_cached.timestamp).total_seconds()
            if age < 3600:  # 1小时内有效
                return ah_cached
        
        # 2. 尝试从IB客户端获取盘后快照
        if self._ib_connected and self.ib_client:
            snapshot = self.ib_client.get_after_hours_snapshot(symbol)
            if snapshot:
                quote = Quote(
                    symbol=symbol,
                    price=snapshot["price"],
                    change_pct=snapshot.get("change_pct", 0),
                    timestamp=datetime.fromisoformat(snapshot["timestamp"]) if isinstance(snapshot.get("timestamp"), str) else datetime.now(),
                    source="ib_after_hours",
                    close=snapshot.get("close"),
                    session="after_hours",
                    is_realtime=False,
                    is_extended_hours=True
                )
                with self._cache_lock:
                    self._after_hours_cache[symbol] = quote
                return quote
        
        # 3. 从文件读取历史盘后数据（IB保存的数据）
        snapshot_dir = Path(__file__).parent / "after_hours_snapshots"
        if snapshot_dir.exists():
            files = sorted(snapshot_dir.glob("ah_snapshot_*.json"), reverse=True)
            if files:
                try:
                    with open(files[0]) as f:
                        snapshot = json.load(f)
                        if symbol in snapshot.get("quotes", {}):
                            q = snapshot["quotes"][symbol]
                            quote = Quote(
                                symbol=symbol,
                                price=q["price"],
                                change_pct=q.get("change_pct", 0),
                                timestamp=datetime.strptime(snapshot["date"], "%Y%m%d"),
                                source=f"ib_after_hours_file:{files[0].name}",
                                close=q.get("close"),
                                session="after_hours",
                                is_extended_hours=True
                            )
                            return quote
                except Exception:
                    pass
        
        return None
    
    def get_a_share_open_forecast(self, symbol: str = "XOP") -> Optional[Dict[str, Any]]:
        """
        获取A股开盘预估信息 - 仅使用IB盘后数据
        """
        # 获取盘后参考价
        ah_quote = self.get_after_hours_reference(symbol)
        if not ah_quote:
            return None
        
        # 获取常规收盘价
        regular_close = ah_quote.close
        if not regular_close and self._ib_connected:
            regular_close = self.ib_client.get_regular_close(symbol)
        
        if not regular_close:
            regular_close = ah_quote.price / (1 + ah_quote.change_pct / 100) if ah_quote.change_pct else ah_quote.price
        
        # 计算盘后涨跌幅
        ah_change_pct = ((ah_quote.price - regular_close) / regular_close * 100) if regular_close else 0
        
        # 预估华宝油气净值变化（95%仓位）
        forecast_nav_change = ah_change_pct * 0.95
        
        # 判断数据可靠性
        hours_ago = (datetime.now() - ah_quote.timestamp).total_seconds() / 3600
        if hours_ago < 2:
            reliability = "high"
        elif hours_ago < 12:
            reliability = "medium"
        else:
            reliability = "low"
        
        return {
            "symbol": symbol,
            "after_hours_price": ah_quote.price,
            "regular_close": regular_close,
            "after_hours_change_pct": round(ah_change_pct, 2),
            "forecast_nav_change": round(forecast_nav_change, 2),
            "data_time": ah_quote.timestamp.isoformat(),
            "reliability": reliability,
            "hours_ago": round(hours_ago, 1)
        }
    
    def _fetch_from_ib(self, symbol: str) -> Optional[Quote]:
        """从IB获取行情"""
        if not self._ib_connected or not self.ib_client:
            return None
        
        try:
            # 确保已订阅
            if symbol not in self.ib_client.subscriptions:
                self.ib_client.subscribe(symbol, include_extended=True)
                time.sleep(0.5)
            
            tick = self.ib_client.get_latest_tick(symbol)
            if tick and tick.last:
                return Quote(
                    symbol=tick.symbol,
                    price=tick.last,
                    change_pct=tick.change_pct or 0,
                    timestamp=tick.timestamp,
                    source="ib_realtime",
                    latency_ms=0,
                    bid=tick.bid,
                    ask=tick.ask,
                    volume=tick.volume,
                    high=tick.high,
                    low=tick.low,
                    close=tick.close,
                    session=tick.session,
                    is_realtime=True,
                    is_extended_hours=tick.session in ["pre_market", "after_hours"]
                )
        except Exception as e:
            print(f"❌ IB获取行情失败 ({symbol}): {e}")
        
        return None
    
    def get_usd_cny_rate(self) -> Optional[float]:
        """获取USD/CNY汇率 - 仅使用IB数据源"""
        # 尝试从IB获取（如果IB支持外汇行情）
        if self._ib_connected and self.ib_client:
            try:
                # 订阅USDCNY外汇对
                if "USDCNH" not in self.ib_client.subscriptions:
                    self.ib_client.subscribe("USDCNH", sec_type="CASH", exchange="IDEALPRO")
                    time.sleep(0.5)
                
                tick = self.ib_client.get_latest_tick("USDCNH")
                if tick and tick.last:
                    return tick.last
            except Exception:
                pass
        
        # 如果没有IB数据，返回None（不做降级到新浪财经）
        return None
    
    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        session_info = TradingHours.get_session_info() if HAS_IB else {}
        
        status = {
            "ib_connected": self._ib_connected,
            "ib_host": self.ib_host,
            "ib_port": self.ib_port,
            "cached_symbols": list(self._cache.keys()),
            "after_hours_cached": list(self._after_hours_cache.keys()),
            "trading_session": session_info,
            "stats": dict(self._stats),
        }
        
        if self._ib_connected and self.ib_client:
            status["ib_status"] = self.ib_client.get_connection_status()
        
        return status
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        return dict(self._stats)
    
    def close(self):
        """关闭连接"""
        if self.ib_client:
            self.ib_client.stop()
            self._ib_connected = False


# ============ 集成函数 ============

def create_quote_manager(auto_connect: bool = True) -> QuoteManager:
    """创建行情管理器"""
    return QuoteManager(auto_connect=auto_connect)


def get_xop_for_lof_arbitrage(qm: QuoteManager) -> Dict[str, Any]:
    """
    专为LOF套利优化的XOP行情获取 - 仅使用IB数据源
    """
    session = TradingHours.get_session()
    
    # 获取当前行情
    quote = qm.get_quote("XOP")
    
    result = {
        "symbol": "XOP",
        "has_realtime_data": False,
        "has_after_hours_data": False,
        "recommendation": ""
    }
    
    if quote:
        result.update({
            "price": quote.price,
            "change_pct": quote.change_pct,
            "source": quote.source,
            "session": quote.session,
            "timestamp": quote.timestamp.isoformat(),
        })
        
        if quote.is_realtime:
            result["has_realtime_data"] = True
            result["recommendation"] = "✅ 使用IB实时数据"
        elif quote.is_extended_hours:
            result["has_after_hours_data"] = True
            result["recommendation"] = "⚠️ IB盘后数据"
    else:
        result["recommendation"] = "❌ IB数据获取失败，建议不交易"
    
    # 如果休市，获取开盘预估
    if session == TradingSession.CLOSED:
        forecast = qm.get_a_share_open_forecast("XOP")
        if forecast:
            result["a_share_forecast"] = forecast
            result["recommendation"] = f"📊 基于IB盘后数据预估A股开盘净值变化: {forecast['forecast_nav_change']:+.2f}%"
    
    return result


# ============ 测试代码 ============

def test_quote_manager():
    """测试行情管理器"""
    print("=" * 70)
    print("行情管理器测试 - IB专用版")
    print("=" * 70)
    
    # 打印交易时段信息
    if HAS_IB:
        print("\n📅 当前交易时段信息:")
        info = TradingHours.get_session_info()
        for key, value in info.items():
            print(f"  {key}: {value}")
    
    # 创建管理器
    print("\n🔌 初始化行情管理器...")
    qm = QuoteManager(auto_connect=True)
    
    # 检查IB连接
    status = qm.get_connection_status()
    print(f"  IB连接: {'✅' if status['ib_connected'] else '❌'}")
    
    if not status['ib_connected']:
        print("\n❌ IB未连接，系统无法获取数据，建议不交易")
        qm.close()
        return
    
    # 获取XOP行情
    print("\n📊 获取 XOP 行情...")
    xop = qm.get_quote("XOP")
    if xop:
        rt_marker = "⚡实时" if xop.is_realtime else "⏱️延时"
        ah_marker = "🌙盘后" if xop.is_extended_hours else ""
        print(f"  价格: ${xop.price:.2f}")
        print(f"  涨跌: {xop.change_pct:+.2f}%")
        print(f"  数据源: {xop.source} {rt_marker} {ah_marker}")
        print(f"  时段: {xop.session}")
    else:
        print("  ❌ IB获取失败，建议不交易")
    
    # 获取盘后参考价
    print("\n🌙 获取盘后收盘参考价...")
    ah = qm.get_after_hours_reference("XOP")
    if ah:
        print(f"  盘后价格: ${ah.price:.2f}")
        print(f"  数据来源: {ah.source}")
    else:
        print("  暂无盘后数据")
    
    # 获取A股开盘预估
    print("\n🇨🇳 获取A股开盘预估...")
    forecast = qm.get_a_share_open_forecast("XOP")
    if forecast:
        print(f"  美股常规收盘: ${forecast['regular_close']:.2f}")
        print(f"  美股盘后收盘: ${forecast['after_hours_price']:.2f}")
        print(f"  盘后涨跌幅: {forecast['after_hours_change_pct']:+.2f}%")
        print(f"  预估净值变化: {forecast['forecast_nav_change']:+.2f}%")
        print(f"  数据可靠性: {forecast['reliability']}")
    else:
        print("  无法获取预估数据")
    
    # LOF套利专用接口
    print("\n🎯 LOF套利专用接口...")
    lof_data = get_xop_for_lof_arbitrage(qm)
    print(f"  推荐: {lof_data.get('recommendation', 'N/A')}")
    
    # 统计
    print("\n📈 统计:")
    stats = qm.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    qm.close()
    print("\n✅ 测试完成")


if __name__ == "__main__":
    test_quote_manager()
