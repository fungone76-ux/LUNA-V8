"""
LunaDebugTracer - Sistema di verifica automatica per Luna RPG v4

Traccia ogni passaggio del game loop e confronta EXPECTED vs ACTUAL.
Genera log dettagliato per diagnosticare discrepanze.
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum


class CheckStatus(Enum):
    """Stato di un check."""
    PASS = "[PASS]"
    FAIL = "[FAIL]"
    SKIP = "[SKIP]"
    INFO = "[INFO]"


@dataclass
class DebugCheck:
    """Singolo check di verifica."""
    component: str
    check_name: str
    expected: Any
    actual: Any
    status: CheckStatus
    details: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "component": self.component,
            "check": self.check_name,
            "expected": str(self.expected),
            "actual": str(self.actual),
            "status": self.status.value,
            "details": self.details,
        }


@dataclass
class TurnTrace:
    """Traccia di un intero turno."""
    turn_number: int
    user_input: str
    checks: List[DebugCheck] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    
    def add_check(self, check: DebugCheck):
        self.checks.append(check)
    
    def get_failures(self) -> List[DebugCheck]:
        return [c for c in self.checks if c.status == CheckStatus.FAIL]
    
    def finalize(self):
        self.end_time = datetime.now()
    
    def to_dict(self) -> Dict:
        return {
            "turn": self.turn_number,
            "user_input": self.user_input,
            "start": self.start_time.isoformat(),
            "end": self.end_time.isoformat() if self.end_time else None,
            "checks": [c.to_dict() for c in self.checks],
            "failures_count": len(self.get_failures()),
        }


class LunaDebugTracer:
    """
    Tracer centrale per debug di Luna RPG v4.
    
    Uso:
        from luna.core.debug_tracer import tracer
        
        # Modo 1: Decoratore
        @tracer.step("Movement Detection")
        def detect_movement(self, input):
            tracer.expect("pattern_match", True)
            result = self._detect(input)
            tracer.actual("pattern_match", result)
            return result
        
        # Modo 2: Context manager
        with tracer.step_context("Image Generation"):
            tracer.expect("companion", "_solo_")
            result = generate()
            tracer.actual("image_generated", result is not None)
    """
    
    def __init__(self):
        self.enabled = False
        self.current_turn: Optional[TurnTrace] = None
        self.turns: List[TurnTrace] = []
        self.current_component: str = ""
        self.current_step: str = ""
        self._expectations: Dict[str, Any] = {}
        
        # Setup logging
        self.logger = logging.getLogger("LunaDebug")
        self.logger.setLevel(logging.DEBUG)
        
        # File handler with UTF-8 encoding
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        self.log_file = log_dir / "luna_debug.log"
        file_handler = logging.FileHandler(self.log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '[%(asctime)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Console handler (solo ERROR) with UTF-8 encoding
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.ERROR)
        console_handler.setFormatter(formatter)
        # Force UTF-8 for console
        if sys.platform == 'win32':
            import io
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        self.logger.addHandler(console_handler)
        
        # Error summary file
        self.error_file = log_dir / "luna_errors.log"
        
    def enable(self):
        """Attiva il tracing."""
        self.enabled = True
        self._log("=== LUNA DEBUG TRACER ENABLED ===")
        
    def disable(self):
        """Disattiva il tracing."""
        self.enabled = False
        self._log("=== LUNA DEBUG TRACER DISABLED ===")
        
    def is_enabled(self) -> bool:
        return self.enabled
    
    def _log(self, message: str, level: int = logging.DEBUG):
        """Log interno."""
        if self.enabled:
            self.logger.log(level, message)
    
    def start_turn(self, turn_number: int, user_input: str):
        """Inizia tracciamento di un nuovo turno."""
        if not self.enabled:
            return
            
        # Finalizza turno precedente se esiste
        if self.current_turn:
            self.finalize_turn()
            
        self.current_turn = TurnTrace(
            turn_number=turn_number,
            user_input=user_input
        )
        self._log(f"\n{'='*60}")
        self._log(f"=== TURN {turn_number} START ===")
        self._log(f"[INPUT] '{user_input}'")
        self._log(f"{'='*60}")
        
    def finalize_turn(self):
        """Finalizza turno corrente."""
        if not self.enabled or not self.current_turn:
            return
            
        self.current_turn.finalize()
        failures = self.current_turn.get_failures()
        
        self._log(f"\n{'='*60}")
        self._log(f"=== TURN {self.current_turn.turn_number} END ===")
        self._log(f"Checks: {len(self.current_turn.checks)}, Failures: {len(failures)}")
        
        if failures:
            self._log("FAILURES:", logging.ERROR)
            for f in failures:
                self._log(f"  - [{f.component}] {f.check_name}: {f.details}", logging.ERROR)
        
        self._log(f"{'='*60}\n")
        
        # Salva turno
        self.turns.append(self.current_turn)
        
        # Scrive errori su file separato
        if failures:
            with open(self.error_file, 'a', encoding='utf-8') as f:
                f.write(f"\n[Turn {self.current_turn.turn_number}] '{self.current_turn.user_input}'\n")
                for fail in failures:
                    f.write(f"  [{fail.component}] {fail.check_name}: {fail.details}\n")
                    f.write(f"    Expected: {fail.expected}\n")
                    f.write(f"    Actual:   {fail.actual}\n")
        
        self.current_turn = None
        
    def step(self, step_name: str, component: str = ""):
        """Decoratore per tracciare una funzione."""
        def decorator(func: Callable):
            def wrapper(*args, **kwargs):
                if not self.enabled:
                    return func(*args, **kwargs)
                    
                comp = component or func.__module__.split('.')[-1]
                with self.step_context(step_name, comp):
                    return func(*args, **kwargs)
            return wrapper
        return decorator
    
    @contextmanager
    def step_context(self, step_name: str, component: str = ""):
        """Context manager per un passaggio."""
        if not self.enabled:
            yield
            return
            
        self.current_step = step_name
        self.current_component = component or "Unknown"
        self._expectations = {}
        
        self._log(f"\n[STEP: {step_name}]")
        
        try:
            yield
        except Exception as e:
            self._log(f"EXCEPTION in {step_name}: {e}", logging.ERROR)
            self.check(
                f"{step_name}_exception",
                "No exception",
                f"{type(e).__name__}: {e}",
                CheckStatus.FAIL,
                traceback.format_exc()
            )
            raise
        finally:
            self.current_step = ""
            self._expectations = {}
    
    def expect(self, check_name: str, expected_value: Any, details: str = ""):
        """Dichiara valore atteso."""
        if not self.enabled:
            return
        self._expectations[check_name] = (expected_value, details)
        self._log(f"  EXPECTED: {check_name} = {expected_value}")
    
    def actual(self, check_name: str, actual_value: Any, details: str = ""):
        """Registra valore effettivo e confronta con atteso."""
        if not self.enabled:
            return
            
        expected = None
        expected_details = ""
        if check_name in self._expectations:
            expected, expected_details = self._expectations[check_name]
        
        # Determina stato
        if expected is not None:
            if actual_value == expected:
                status = CheckStatus.PASS
            else:
                status = CheckStatus.FAIL
        else:
            status = CheckStatus.INFO
        
        # Crea check
        check = DebugCheck(
            component=self.current_component,
            check_name=f"{self.current_step}.{check_name}",
            expected=expected,
            actual=actual_value,
            status=status,
            details=details or expected_details
        )
        
        if self.current_turn:
            self.current_turn.add_check(check)
        
        # Log
        icon = status.value
        self._log(f"  ACTUAL:   {check_name} = {actual_value} {icon}")
        if status == CheckStatus.FAIL:
            self._log(f"  MISMATCH: Expected {expected}, got {actual_value}", logging.ERROR)
        
        return check
    
    def check(self, check_name: str, expected: Any, actual: Any, 
              status: CheckStatus, details: str = ""):
        """Registra un check completo manualmente."""
        if not self.enabled:
            return
            
        check = DebugCheck(
            component=self.current_component,
            check_name=f"{self.current_step}.{check_name}",
            expected=expected,
            actual=actual,
            status=status,
            details=details
        )
        
        if self.current_turn:
            self.current_turn.add_check(check)
        
        icon = status.value
        self._log(f"  [{icon}] {check_name}: {details}")
        if status == CheckStatus.FAIL:
            self._log(f"      Expected: {expected}", logging.ERROR)
            self._log(f"      Actual:   {actual}", logging.ERROR)
        
        return check
    
    def info(self, message: str):
        """Log informativo."""
        if self.enabled:
            self._log(f"  [INFO] {message}")
    
    def warning(self, message: str):
        """Log warning."""
        if self.enabled:
            self._log(f"  [WARN] {message}", logging.WARNING)
    
    def error(self, message: str):
        """Log errore."""
        if self.enabled:
            self._log(f"  [ERROR] {message}", logging.ERROR)
    
    def critical_alert(self, title: str, message: str):
        """Allarme critico - mostra popup o logga pesantemente."""
        if not self.enabled:
            return
            
        alert = f"\n{'!'*60}\nCRITICAL ALERT: {title}\n{message}\n{'!'*60}\n"
        self._log(alert, logging.CRITICAL)
        
        # Scrive su file errori
        with open(self.error_file, 'a', encoding='utf-8') as f:
            f.write(f"\n{'!'*60}\n")
            f.write(f"CRITICAL ALERT: {title}\n")
            f.write(f"{message}\n")
            f.write(f"{'!'*60}\n\n")
    
    def get_summary(self) -> Dict:
        """Restituisce riassunto di tutti i turni."""
        total_checks = sum(len(t.checks) for t in self.turns)
        total_failures = sum(len(t.get_failures()) for t in self.turns)
        
        return {
            "total_turns": len(self.turns),
            "total_checks": total_checks,
            "total_failures": total_failures,
            "success_rate": (total_checks - total_failures) / total_checks if total_checks > 0 else 0,
            "turns": [t.to_dict() for t in self.turns],
        }
    
    def save_summary(self, filepath: Optional[str] = None):
        """Salva riassunto su file JSON."""
        if not self.enabled:
            return
            
        path = filepath or "logs/luna_summary.json"
        summary = self.get_summary()
        
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False)
        
        self._log(f"Summary saved to {path}")


# Istanza globale
tracer = LunaDebugTracer()


def enable_debug():
    """Attiva debug tracing."""
    tracer.enable()
    
def disable_debug():
    """Disattiva debug tracing."""
    tracer.disable()
    
def is_debug_enabled() -> bool:
    """Verifica se debug è attivo."""
    return tracer.is_enabled()
