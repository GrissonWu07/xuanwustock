"""Unified quant simulation workflow for the gateway-backed application."""

__all__ = [
    "CandidatePoolService",
    "Decision",
    "LotStatus",
    "PortfolioService",
    "PositionLot",
    "QuantSimDB",
    "QuantSimEngine",
    "QuantSimScheduler",
    "SignalCenterService",
]


def __getattr__(name: str):
    if name == "Decision":
        from app.quant_kernel.models import Decision

        globals()[name] = Decision
        return Decision
    if name in {"LotStatus", "PositionLot"}:
        from app.quant_kernel import portfolio_engine

        value = getattr(portfolio_engine, name)
        globals()[name] = value
        return value
    module_by_name = {
        "CandidatePoolService": "app.quant_sim.candidate_pool_service",
        "QuantSimDB": "app.quant_sim.db",
        "QuantSimEngine": "app.quant_sim.engine",
        "PortfolioService": "app.quant_sim.portfolio_service",
        "QuantSimScheduler": "app.quant_sim.scheduler",
        "SignalCenterService": "app.quant_sim.signal_center_service",
    }
    module_name = module_by_name.get(name)
    if module_name:
        from importlib import import_module

        value = getattr(import_module(module_name), name)
        globals()[name] = value
        return value
    raise AttributeError(name)
