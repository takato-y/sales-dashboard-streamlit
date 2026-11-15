"""テスト共通設定。リポジトリ直下をインポートパスに加える。"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
