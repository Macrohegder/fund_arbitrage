#!/usr/bin/env python3
"""
IB 实时行情客户端 - 支持盘前盘后数据
=====================================
基于 ibapi 的实时行情订阅，支持 XOP、SPY、XBI 等海外 ETF
支持美股常规交易时段、盘前(Pre-market)、盘后(After-hours)数据

Features:
- 多品种实时tick订阅（含盘前盘后）
- 自动重连机制
- 行情数据缓存（含盘后收盘快照）
- 交易时段判断
- 异步数据推送

Usage:
    # 方式1: 直接运行测试
    python ib_realtime_client.py
    
    # 方式2: 集成到其他模块
    from ib_realtime_client import IBRealtimeClient, TradingHours
    
    client = IBRealtimeClient(host="127.0.0.1", port=4002)
    client.subscribe("XOP", callback=on_xop_tick, include_extended=True)
    client.start()
"""

import json
import time
import threading
import queue
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Callable, Any
from dataclasses import dataclass, asdict
from enum import Enum
import pytz

# IB API
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
from ibapi.common import TickAttrib


class TickType(Enum):
    """IB Tick Type 定义"""
    BID_PRICE = 1
    ASK_PRICE = 2
    LAST_PRICE = 4
    HIGH = 6
    LOW = 7
    VOLUME = 8
    CLOSE = 9
    BID_SIZE = 0
    ASK_SIZE = 3
    LAST_SIZE = 5


class TradingSession(Enum):
    """交易时段"""
    PRE_MARKET = "pre_market"      # 盘前 04:00-09:30 ET
    REGULAR = "regular"            # 常规 09:30-16:00 ET
    AFTER_HOURS = "after_hours"    # 盘后 16:00-20:00 ET
    CLOSED = "closed"              # 休市


@dataclass
class TickData:
    """Tick数据结构"""
    symbol: str
    timestamp: datetime
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None  # 昨日收盘价
    volume: Optional[int] = None
    bid_size: Optional[int] = None
    ask_size: Optional[int] = None
    last_size: Optional[int] = None
    session: str = "unknown"       # 数据来源时段
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "timestamp": self.timestamp.isoformat(),
            "bid": self.bid,
            "ask": self.ask,
            "last": self.last,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "bid_size": self.bid_size,
            "ask_size": self.ask_size,
            "last_size": self.last_size,
            "session": self.session,
        }
    
    @property
    def mid_price(self) -> Optional[float]:
        """中间价"""
        if self.bid is not None and self.ask is not None:
            return (self.bid + self.ask) / 2
        return self.last
    
    @property
    def change_pct(self) -> Optional[float]:
        """涨跌幅 %（基于昨收）"""
        if self.last and self.close and self.close > 0:
            return (self.last - self.close) / self.close * 100
        return None
    
    @property
    def extended_change_pct(self) -> Optional[float]:
        """盘后/盘前涨跌幅 %（基于常规收盘价）"""
        if self.last and self.close and self.close > 0:
            return (self.last - self.close) / self.close * 100
        return None


class TradingHours:
    """
    美股交易时段判断工具
    """
    
    # 美东时区
    TZ_ET = pytz.timezone('US/Eastern')
    # 北京时区
    TZ_BEIJING = pytz.timezone('Asia/Shanghai')
    
    @classmethod
    def get_et_time(cls, dt: Optional[datetime] = None) -> datetime:
        """获取美东时间"""
        if dt is None:
            dt = datetime.now()
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(cls.TZ_ET)
    
    @classmethod
    def get_beijing_time(cls, dt: Optional[datetime] = None) -> datetime:
        """获取北京时间"""
        if dt is None:
            dt = datetime.now()
        if dt.tzinfo is None:
            dt = pytz.utc.localize(dt)
        return dt.astimezone(cls.TZ_BEIJING)
    
    @classmethod
    def get_session(cls, dt: Optional[datetime] = None) -> TradingSession:
        """
        判断当前处于哪个交易时段（美东时间）
        """
        et_time = cls.get_et_time(dt)
        time_str = et_time.strftime("%H:%M")
        weekday = et_time.weekday()
        
        # 周末休市
        if weekday >= 5:  # 周六=5, 周日=6
            return TradingSession.CLOSED
        
        # 判断时段
        if "04:00" <= time_str < "09:30":
            return TradingSession.PRE_MARKET
        elif "09:30" <= time_str < "16:00":
            return TradingSession.REGULAR
        elif "16:00" <= time_str < "20:00":
            return TradingSession.AFTER_HOURS
        else:
            return TradingSession.CLOSED
    
    @classmethod
    def get_session_info(cls, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """获取详细的时段信息"""
        et_time = cls.get_et_time(dt)
        beijing_time = cls.get_beijing_time(dt)
        session = cls.get_session(dt)
        
        # 计算A股开盘时间
        a_share_open = beijing_time.replace(hour=9, minute=30, second=0, microsecond=0)
        if beijing_time > a_share_open:
            a_share_open += timedelta(days=1)
        time_to_a_share = (a_share_open - beijing_time).total_seconds() / 3600
        
        return {
            "session": session.value,
            "et_time": et_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "beijing_time": beijing_time.strftime("%Y-%m-%d %H:%M:%S %Z"),
            "is_trading_hours": session in [TradingSession.REGULAR, TradingSession.PRE_MARKET, TradingSession.AFTER_HOURS],
            "is_regular_hours": session == TradingSession.REGULAR,
            "is_extended_hours": session in [TradingSession.PRE_MARKET, TradingSession.AFTER_HOURS],
            "hours_to_a_share_open": round(time_to_a_share, 1),
        }
    
    @classmethod
    def format_beijing_trading_hours(cls) -> str:
        """返回北京时间的美股交易时段"""
        # 夏令时 (3月-11月)
        summer = """美股夏令时 (北京时间):
  盘前: 16:00 - 21:30
  常规: 21:30 - 04:00(+1)
  盘后: 04:00(+1) - 08:00(+1)"""
        
        # 冬令时 (11月-3月)
        winter = """美股冬令时 (北京时间):
  盘前: 17:00 - 22:30
  常规: 22:30 - 05:00(+1)
  盘后: 05:00(+1) - 09:00(+1)"""
        
        return summer + "\n\n" + winter


class IBRealtimeWrapper(EWrapper):
    """IB API 回调处理器"""
    
    def __init__(self, data_queue: queue.Queue, error_queue: queue.Queue):
        super().__init__()
        self.data_queue = data_queue
        self.error_queue = error_queue
        self.next_req_id = 1
        self.symbol_map: Dict[int, str] = {}  # reqId -> symbol
        self.tick_cache: Dict[str, TickData] = {}  # symbol -> TickData
        
        # 盘后数据缓存 - 保存各时段收盘价
        self.after_hours_close: Dict[str, float] = {}  # symbol -> close price
        self.regular_close: Dict[str, float] = {}      # symbol -> regular close
        self.last_update: Dict[str, datetime] = {}     # symbol -> last update
        
    def nextValidId(self, orderId: int):
        """连接成功回调"""
        print(f"✅ IB 连接成功 (Next Valid ID: {orderId})")
        self.next_req_id = orderId
        
    def error(self, reqId: int, errorCode: int, errorString: str, advancedOrderRejectJson: str = ""):
        """错误回调"""
        error_msg = f"IB Error {errorCode}: {errorString}"
        if reqId != -1:
            error_msg = f"[Req {reqId}] {error_msg}"
        
        # 过滤一些常见的非致命错误
        if errorCode in [2104, 2106, 2107, 2108]:  # 市场数据连接状态
            print(f"ℹ️ {error_msg}")
        elif errorCode == 354:  # 请求的数据不可用
            print(f"⚠️ {error_msg}")
        else:
            print(f"❌ {error_msg}")
            self.error_queue.put({
                "req_id": reqId,
                "code": errorCode,
                "message": errorString,
                "timestamp": datetime.now()
            })
    
    def tickPrice(self, reqId: int, tickType: int, price: float, attrib: TickAttrib):
        """价格tick回调"""
        symbol = self.symbol_map.get(reqId)
        if not symbol:
            return
            
        # 获取当前交易时段
        session = TradingHours.get_session().value
            
        # 获取或创建tick数据
        tick = self.tick_cache.get(symbol)
        if tick is None:
            tick = TickData(symbol=symbol, timestamp=datetime.now(), session=session)
            self.tick_cache[symbol] = tick
        
        tick.timestamp = datetime.now()
        tick.session = session
        
        # 更新对应字段
        if tickType == TickType.BID_PRICE.value:
            tick.bid = price
        elif tickType == TickType.ASK_PRICE.value:
            tick.ask = price
        elif tickType == TickType.LAST_PRICE.value:
            tick.last = price
            self.last_update[symbol] = datetime.now()
        elif tickType == TickType.HIGH.value:
            tick.high = price
        elif tickType == TickType.LOW.value:
            tick.low = price
        elif tickType == TickType.CLOSE.value:
            tick.close = price
            # 记录常规收盘价（用于计算盘后涨跌）
            if TradingHours.get_session() == TradingSession.REGULAR:
                self.regular_close[symbol] = price
            
        # 推送到队列
        self.data_queue.put(tick)
    
    def tickSize(self, reqId: int, tickType: int, size: int):
        """成交量tick回调"""
        symbol = self.symbol_map.get(reqId)
        if not symbol:
            return
            
        session = TradingHours.get_session().value
        tick = self.tick_cache.get(symbol)
        if tick is None:
            tick = TickData(symbol=symbol, timestamp=datetime.now(), session=session)
            self.tick_cache[symbol] = tick
            
        tick.timestamp = datetime.now()
        tick.session = session
        
        if tickType == TickType.BID_SIZE.value:
            tick.bid_size = size
        elif tickType == TickType.ASK_SIZE.value:
            tick.ask_size = size
        elif tickType == TickType.LAST_SIZE.value:
            tick.last_size = size
        elif tickType == TickType.VOLUME.value:
            tick.volume = size
            
        self.data_queue.put(tick)


class IBRealtimeClient:
    """
    IB 实时行情客户端 - 支持盘前盘后
    
    Usage:
        client = IBRealtimeClient(host="127.0.0.1", port=4002)
        
        # 订阅常规+盘后数据
        client.subscribe("XOP", callback=on_tick, include_extended=True)
        client.start()
        
        # 获取盘后收盘快照
        snapshot = client.get_after_hours_snapshot("XOP")
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4002,
        client_id: int = 10,
        reconnect_interval: int = 10
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.reconnect_interval = reconnect_interval
        
        # 数据队列
        self.data_queue: queue.Queue[TickData] = queue.Queue()
        self.error_queue: queue.Queue[Dict] = queue.Queue()
        
        # IB客户端
        self.wrapper = IBRealtimeWrapper(self.data_queue, self.error_queue)
        self.client = EClient(self.wrapper)
        
        # 订阅管理
        self.subscriptions: Dict[str, Dict] = {}
        self._callbacks: Dict[str, Callable[[TickData], None]] = {}
        
        # 运行状态
        self._running = False
        self._connected = False
        self._thread: Optional[threading.Thread] = None
        self._process_thread: Optional[threading.Thread] = None
        
        # 盘后数据保存线程
        self._snapshot_thread: Optional[threading.Thread] = None
        
    def _create_contract(
        self,
        symbol: str,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD"
    ) -> Contract:
        """创建IB合约对象"""
        contract = Contract()
        contract.symbol = symbol
        contract.secType = sec_type
        contract.exchange = exchange
        contract.currency = currency
        return contract
    
    def subscribe(
        self,
        symbol: str,
        callback: Optional[Callable[[TickData], None]] = None,
        sec_type: str = "STK",
        exchange: str = "SMART",
        currency: str = "USD",
        include_extended: bool = True
    ) -> bool:
        """
        订阅指定symbol的实时行情
        
        Args:
            symbol: 股票代码
            callback: 可选的回调函数
            sec_type: 证券类型
            exchange: 交易所
            currency: 货币
            include_extended: 是否包含盘前盘后数据
        """
        if symbol in self.subscriptions:
            print(f"⚠️ {symbol} 已经订阅")
            return True
            
        if not self._connected:
            print(f"⚠️ 未连接IB，将在连接后自动订阅 {symbol}")
            self.subscriptions[symbol] = {
                "pending": True,
                "callback": callback,
                "sec_type": sec_type,
                "exchange": exchange,
                "currency": currency,
                "include_extended": include_extended
            }
            if callback:
                self._callbacks[symbol] = callback
            return True
        
        try:
            contract = self._create_contract(symbol, sec_type, exchange, currency)
            req_id = self.wrapper.next_req_id
            
            # 请求市场数据
            # genericTickList="233" 请求盘后数据
            tick_list = "233" if include_extended else ""
            self.client.reqMktData(req_id, contract, tick_list, False, False, [])
            
            self.wrapper.symbol_map[req_id] = symbol
            self.subscriptions[symbol] = {
                "req_id": req_id,
                "contract": contract,
                "callback": callback,
                "include_extended": include_extended,
                "subscribed_at": datetime.now()
            }
            
            if callback:
                self._callbacks[symbol] = callback
                
            print(f"✅ 已订阅 {symbol} (ReqID: {req_id}, 盘后数据: {include_extended})")
            self.wrapper.next_req_id += 1
            return True
            
        except Exception as e:
            print(f"❌ 订阅 {symbol} 失败: {e}")
            return False
    
    def unsubscribe(self, symbol: str) -> bool:
        """取消订阅"""
        if symbol not in self.subscriptions:
            return False
            
        sub = self.subscriptions[symbol]
        if "req_id" in sub:
            self.client.cancelMktData(sub["req_id"])
            
        del self.subscriptions[symbol]
        if symbol in self._callbacks:
            del self._callbacks[symbol]
            
        print(f"✅ 已取消订阅 {symbol}")
        return True
    
    def connect(self) -> bool:
        """连接到IB Gateway"""
        try:
            print(f"🔌 正在连接 IB Gateway {self.host}:{self.port}...")
            self.client.connect(self.host, self.port, self.client_id)
            
            # 启动IB事件循环
            self._thread = threading.Thread(target=self.client.run, daemon=True)
            self._thread.start()
            
            # 等待连接确认
            for i in range(50):
                if self.client.isConnected():
                    self._connected = True
                    self._process_pending_subscriptions()
                    return True
                time.sleep(0.1)
                
            print("❌ 连接超时")
            return False
            
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            return False
    
    def _process_pending_subscriptions(self):
        """处理连接前pending的订阅请求"""
        pending = [(s, cfg) for s, cfg in self.subscriptions.items() if cfg.get("pending")]
        for symbol, cfg in pending:
            self.subscribe(
                symbol,
                callback=cfg.get("callback"),
                sec_type=cfg.get("sec_type", "STK"),
                exchange=cfg.get("exchange", "SMART"),
                currency=cfg.get("currency", "USD"),
                include_extended=cfg.get("include_extended", True)
            )
            if symbol in self.subscriptions:
                self.subscriptions[symbol].pop("pending", None)
    
    def disconnect(self):
        """断开连接"""
        self._running = False
        self._connected = False
        self.client.disconnect()
        print("🔌 IB 连接已断开")
    
    def start(self):
        """启动客户端"""
        if not self.connect():
            raise ConnectionError("无法连接到IB Gateway")
        
        self._running = True
        
        # 启动数据处理线程
        self._process_thread = threading.Thread(target=self._process_loop, daemon=True)
        self._process_thread.start()
        
        # 启动盘后数据快照线程
        self._snapshot_thread = threading.Thread(target=self._snapshot_loop, daemon=True)
        self._snapshot_thread.start()
        
        print("✅ IB 实时行情客户端已启动")
    
    def stop(self):
        """停止客户端"""
        self._running = False
        self.disconnect()
        print("✅ IB 实时行情客户端已停止")
    
    def _process_loop(self):
        """数据处理循环"""
        while self._running:
            try:
                tick = self.data_queue.get(timeout=1)
                
                # 调用symbol特定的回调
                if tick.symbol in self._callbacks:
                    try:
                        self._callbacks[tick.symbol](tick)
                    except Exception as e:
                        print(f"❌ 回调执行错误 ({tick.symbol}): {e}")
                        
            except queue.Empty:
                continue
            except Exception as e:
                print(f"❌ 数据处理错误: {e}")
    
    def _snapshot_loop(self):
        """
        盘后数据快照线程
        在盘后交易结束时(20:00 ET)保存收盘价作为A股开盘参考
        """
        last_saved_date = None
        
        while self._running:
            try:
                et_time = TradingHours.get_et_time()
                current_date = et_time.date()
                time_str = et_time.strftime("%H:%M")
                session = TradingHours.get_session(et_time)
                
                # 盘后交易结束(20:00 ET)，保存快照
                if session == TradingSession.CLOSED and last_saved_date != current_date:
                    if "20:00" <= time_str < "20:05":
                        print(f"\n💾 保存盘后收盘快照 ({et_time.strftime('%Y-%m-%d %H:%M')} ET)...")
                        self._save_after_hours_snapshot()
                        last_saved_date = current_date
                
                # 每分钟检查一次
                time.sleep(60)
                
            except Exception as e:
                print(f"❌ 快照线程错误: {e}")
                time.sleep(60)
    
    def _save_after_hours_snapshot(self):
        """保存盘后收盘快照"""
        snapshot_dir = Path(__file__).parent / "after_hours_snapshots"
        snapshot_dir.mkdir(exist_ok=True)
        
        et_time = TradingHours.get_et_time()
        date_str = et_time.strftime("%Y%m%d")
        
        snapshot = {
            "date": date_str,
            "et_time": et_time.strftime("%Y-%m-%d %H:%M:%S"),
            "beijing_time": TradingHours.get_beijing_time().strftime("%Y-%m-%d %H:%M:%S"),
            "session": "after_hours_close",
            "quotes": {}
        }
        
        for symbol in self.subscriptions:
            tick = self.wrapper.tick_cache.get(symbol)
            if tick and tick.last:
                snapshot["quotes"][symbol] = {
                    "price": tick.last,
                    "close": tick.close,
                    "change_pct": tick.change_pct,
                    "volume": tick.volume,
                    "session": tick.session
                }
                # 更新盘后收盘价缓存
                self.wrapper.after_hours_close[symbol] = tick.last
        
        # 保存到文件
        file_path = snapshot_dir / f"ah_snapshot_{date_str}.json"
        with open(file_path, "w") as f:
            json.dump(snapshot, f, indent=2)
        
        print(f"✅ 盘后快照已保存: {file_path}")
    
    def get_after_hours_snapshot(self, symbol: str) -> Optional[Dict]:
        """
        获取盘后收盘快照
        用于A股开盘前的净值预估
        """
        # 1. 先检查内存缓存
        if symbol in self.wrapper.after_hours_close:
            return {
                "symbol": symbol,
                "price": self.wrapper.after_hours_close[symbol],
                "source": "memory_cache",
                "timestamp": self.wrapper.last_update.get(symbol)
            }
        
        # 2. 从文件读取
        snapshot_dir = Path(__file__).parent / "after_hours_snapshots"
        if not snapshot_dir.exists():
            return None
        
        # 找最新的快照文件
        files = sorted(snapshot_dir.glob("ah_snapshot_*.json"), reverse=True)
        if files:
            with open(files[0]) as f:
                snapshot = json.load(f)
                if symbol in snapshot.get("quotes", {}):
                    quote = snapshot["quotes"][symbol]
                    return {
                        "symbol": symbol,
                        "price": quote["price"],
                        "close": quote["close"],
                        "change_pct": quote["change_pct"],
                        "source": f"file:{files[0].name}",
                        "snapshot_date": snapshot["date"]
                    }
        
        return None
    
    def get_tick(self, symbol: Optional[str] = None, timeout: float = 1.0) -> Optional[TickData]:
        """从队列获取tick数据"""
        try:
            if symbol is None:
                return self.data_queue.get(timeout=timeout)
            else:
                deadline = time.time() + timeout
                while time.time() < deadline:
                    try:
                        tick = self.data_queue.get(timeout=0.1)
                        if tick.symbol == symbol:
                            return tick
                    except queue.Empty:
                        continue
                return None
        except queue.Empty:
            return None
    
    def get_latest_tick(self, symbol: str) -> Optional[TickData]:
        """获取指定symbol的最新缓存tick"""
        return self.wrapper.tick_cache.get(symbol)
    
    def get_regular_close(self, symbol: str) -> Optional[float]:
        """获取常规交易时段收盘价"""
        return self.wrapper.regular_close.get(symbol)
    
    def get_connection_status(self) -> Dict[str, Any]:
        """获取连接状态"""
        session_info = TradingHours.get_session_info()
        
        return {
            "connected": self._connected and self.client.isConnected(),
            "subscribed_symbols": list(self.subscriptions.keys()),
            "client_id": self.client_id,
            "host": self.host,
            "port": self.port,
            "trading_session": session_info,
        }


# ============ 测试代码 ============

def test_ib_client():
    """测试IB实时行情客户端"""
    print("=" * 70)
    print("IB 实时行情客户端测试 - 含盘前盘后")
    print("=" * 70)
    
    # 打印交易时段信息
    print("\n📅 当前交易时段信息:")
    session_info = TradingHours.get_session_info()
    for key, value in session_info.items():
        print(f"  {key}: {value}")
    
    print("\n" + TradingHours.format_beijing_trading_hours())
    
    # 创建客户端
    client = IBRealtimeClient(host="127.0.0.1", port=4002, client_id=99)
    
    # 定义回调
    def on_xop_tick(tick: TickData):
        change_info = f" ({tick.change_pct:+.2f}%)" if tick.change_pct else ""
        session_icon = {
            "pre_market": "🌅",
            "regular": "☀️",
            "after_hours": "🌙",
            "closed": "🌑"
        }.get(tick.session, "❓")
        
        print(f"[{session_icon} {tick.session}] XOP: ${tick.last:.2f}{change_info} "
              f"| 买卖: {tick.bid}/{tick.ask}")
    
    try:
        # 启动连接
        client.start()
        
        # 订阅XOP（包含盘后数据）
        print("\n📊 订阅 XOP (含盘后数据)...")
        client.subscribe("XOP", callback=on_xop_tick, include_extended=True)
        
        # 运行一段时间接收数据
        print("\n⏳ 接收实时行情中 (按 Ctrl+C 停止)...\n")
        time.sleep(30)
        
        # 测试获取盘后快照
        print("\n📋 盘后快照测试:")
        snapshot = client.get_after_hours_snapshot("XOP")
        if snapshot:
            print(f"  盘后价格: ${snapshot['price']:.2f}")
            print(f"  来源: {snapshot['source']}")
        else:
            print("  暂无盘后快照")
        
    except KeyboardInterrupt:
        print("\n\n⚠️ 用户中断")
    except Exception as e:
        print(f"\n❌ 错误: {e}")
    finally:
        client.stop()
        print("\n✅ 测试完成")


if __name__ == "__main__":
    test_ib_client()
