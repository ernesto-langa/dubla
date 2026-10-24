import sys
from pathlib import Path

# os scripts estão na raiz do projeto (não é um pacote)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
