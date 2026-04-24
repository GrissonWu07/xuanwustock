import sqlite3
import json
from datetime import datetime
import os
from pathlib import Path

from app.runtime_paths import default_db_path


DEFAULT_DB_PATH = str(default_db_path("stock_analysis.db"))

class StockAnalysisDatabase:
    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH):
        """初始化数据库连接"""
        self.db_path = str(db_path)
        # 确保数据库所在目录存在
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
        self.init_database()
    
    def init_database(self):
        """初始化数据库表结构"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 创建分析记录表
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS analysis_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                stock_name TEXT,
                analysis_date TEXT NOT NULL,
                period TEXT NOT NULL,
                stock_info TEXT,
                agents_results TEXT,
                discussion_result TEXT,
                final_decision TEXT,
                indicators TEXT,
                historical_data TEXT,
                created_at TEXT NOT NULL
            )
        ''')
        self._ensure_column(cursor, "analysis_records", "indicators", "TEXT")
        self._ensure_column(cursor, "analysis_records", "historical_data", "TEXT")
        
        conn.commit()
        conn.close()

    @staticmethod
    def _ensure_column(cursor: sqlite3.Cursor, table_name: str, column_name: str, column_type: str) -> None:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {row[1] for row in cursor.fetchall()}
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
    
    def save_analysis(
        self,
        symbol,
        stock_name,
        period,
        stock_info,
        agents_results,
        discussion_result,
        final_decision,
        indicators=None,
        historical_data=None,
    ):
        """保存分析记录到数据库"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # 准备数据
        analysis_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        created_at = datetime.now().isoformat()
        
        # 将复杂对象转换为JSON字符串
        stock_info_json = json.dumps(stock_info, ensure_ascii=False, default=str)
        agents_results_json = json.dumps(agents_results, ensure_ascii=False, default=str)
        discussion_result_json = json.dumps(discussion_result, ensure_ascii=False, default=str)
        final_decision_json = json.dumps(final_decision, ensure_ascii=False, default=str)
        indicators_json = json.dumps(indicators or {}, ensure_ascii=False, default=str)
        historical_data_json = json.dumps(historical_data or [], ensure_ascii=False, default=str)
        
        cursor.execute('''
            INSERT INTO analysis_records 
            (symbol, stock_name, analysis_date, period, stock_info, agents_results, discussion_result, final_decision, indicators, historical_data, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            symbol,
            stock_name,
            analysis_date,
            period,
            stock_info_json,
            agents_results_json,
            discussion_result_json,
            final_decision_json,
            indicators_json,
            historical_data_json,
            created_at,
        ))
        
        conn.commit()
        conn.close()
        
        return cursor.lastrowid
    
    def _build_record_filters(self, search: str | None = None) -> tuple[str, list[str]]:
        keyword = str(search or "").strip()
        if not keyword:
            return "", []
        like_keyword = f"%{keyword}%"
        return (
            "WHERE symbol LIKE ? OR stock_name LIKE ? OR period LIKE ? OR final_decision LIKE ?",
            [like_keyword, like_keyword, like_keyword, like_keyword],
        )

    def _analysis_summary_rows(self, where_sql: str = "", params: list[str] | None = None, *, limit: int | None = None, offset: int = 0):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        sql = f"""
            SELECT id, symbol, stock_name, analysis_date, period, final_decision, created_at
            FROM analysis_records
            {where_sql}
            ORDER BY created_at DESC
        """
        query_params: list[object] = list(params or [])
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            query_params.extend([max(0, int(limit)), max(0, int(offset))])

        cursor.execute(sql, tuple(query_params))
        records = cursor.fetchall()
        conn.close()
        return records

    def _summary_rows_to_records(self, records):
        result = []
        for record in records:
            final_decision = json.loads(record[5]) if record[5] else {}
            rating = final_decision.get('rating', '未知') if isinstance(final_decision, dict) else '未知'

            result.append({
                'id': record[0],
                'symbol': record[1],
                'stock_name': record[2],
                'analysis_date': record[3],
                'period': record[4],
                'rating': rating,
                'created_at': record[6]
            })

        return result

    def get_all_records(self):
        """获取所有分析记录"""
        return self._summary_rows_to_records(self._analysis_summary_rows())

    def get_records_page(self, search: str | None = None, limit: int = 50, offset: int = 0):
        """按页获取分析记录，供 UI 表格分页/搜索使用。"""
        where_sql, params = self._build_record_filters(search)
        return self._summary_rows_to_records(
            self._analysis_summary_rows(where_sql, params, limit=limit, offset=offset)
        )

    def count_records(self, search: str | None = None) -> int:
        """统计分析记录数量，支持与分页查询相同的搜索条件。"""
        where_sql, params = self._build_record_filters(search)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(f"SELECT COUNT(*) FROM analysis_records {where_sql}", tuple(params))
        count = cursor.fetchone()[0]
        conn.close()
        return int(count or 0)
    
    def get_record_count(self):
        """获取记录总数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM analysis_records')
        count = cursor.fetchone()[0]
        conn.close()
        
        return count
    
    def get_record_by_id(self, record_id):
        """根据ID获取详细分析记录"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT * FROM analysis_records WHERE id = ?
            ''',
            (record_id,),
        )

        record = cursor.fetchone()
        conn.close()

        if not record:
            return None

        return self._parse_analysis_row(record)

    def get_latest_record_by_symbol(self, symbol: str):
        """根据股票代码获取最近一次分析记录"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT * FROM analysis_records
            WHERE symbol = ?
            ORDER BY id DESC
            LIMIT 1
            ''',
            (symbol,),
        )

        record = cursor.fetchone()
        conn.close()

        if not record:
            return None

        return self._parse_analysis_row(record)

    def get_recent_records_by_symbol(self, symbol: str, limit: int = 5) -> list[dict]:
        """根据股票代码获取最近几次分析记录"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(
            '''
            SELECT * FROM analysis_records
            WHERE symbol = ?
            ORDER BY id DESC
            LIMIT ?
            ''',
            (symbol, limit),
        )

        records = cursor.fetchall()
        conn.close()

        return [self._parse_analysis_row(record) for record in records]

    @staticmethod
    def _parse_analysis_row(record: sqlite3.Row) -> dict:
        return {
            'id': record['id'],
            'symbol': record['symbol'],
            'stock_name': record['stock_name'],
            'analysis_date': record['analysis_date'],
            'period': record['period'],
            'stock_info': json.loads(record['stock_info']) if record['stock_info'] else {},
            'agents_results': json.loads(record['agents_results']) if record['agents_results'] else {},
            'discussion_result': json.loads(record['discussion_result']) if record['discussion_result'] else {},
            'final_decision': json.loads(record['final_decision']) if record['final_decision'] else {},
            'indicators': json.loads(record['indicators']) if 'indicators' in record.keys() and record['indicators'] else {},
            'historical_data': json.loads(record['historical_data']) if 'historical_data' in record.keys() and record['historical_data'] else [],
            'created_at': record['created_at'],
        }
    
    def delete_record(self, record_id):
        """删除指定记录"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM analysis_records WHERE id = ?', (record_id,))
        conn.commit()
        conn.close()
        
        return cursor.rowcount > 0
    
    def get_record_count(self):
        """获取记录总数"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM analysis_records')
        count = cursor.fetchone()[0]
        conn.close()
        
        return count

# 全局数据库实例
db = StockAnalysisDatabase()
