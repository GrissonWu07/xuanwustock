from __future__ import annotations

from typing import Any, Callable

from app.async_task_base import AsyncTaskManagerBase
from app.i18n import t


class WorkbenchAnalysisTaskManager(AsyncTaskManagerBase):
    def __init__(self, *, limit: int = 200) -> None:
        super().__init__(task_prefix="analysis", title=t("Stock analysis task"), limit=limit)

    def create_task(
        self,
        *,
        codes: list[str],
        selected: list[str],
        cycle: str,
        mode: str,
        now: Callable[[], str],
    ) -> str:
        return super().create_task(
            now=now,
            message=t("Task submitted. Pending analysis for {count} symbols.", count=len(codes)),
            stage="queued",
            progress=0,
            symbol=codes[0] if codes else "",
            codes=codes,
            selected=selected,
            cycle=cycle,
            mode=mode,
            results=[],
            errors=[],
        )

    def run_task(
        self,
        *,
        task_id: str,
        context: Any,
        normalize_code: Callable[[str], str],
        analysis_config_builder: Callable[[list[str]], dict[str, bool]],
        build_payload: Callable[..., dict[str, Any]],
        analyze_stock: Callable[..., dict[str, Any]],
        now: Callable[[], str],
        txt: Callable[[Any, str], str],
        dict_value: Callable[[Any, str, Any], Any],
    ) -> None:
        task = self.get_task(task_id)
        if not task:
            return
        codes = [normalize_code(code) for code in task.get("codes") or [] if txt(code, "")]
        selected = [str(item) for item in task.get("selected") or [] if txt(item, "")]
        cycle = txt(task.get("cycle"), "1y")
        mode = txt(task.get("mode"), t("Batch analysis") if len(codes) > 1 else t("Single analysis"))
        total = max(len(codes), 1)
        self.update_task(
            task_id,
            now=now,
            status="running",
            stage="fetch",
            progress=1,
            symbol=codes[0] if codes else "",
            started_at=now(),
            message=t("Analysis started. Total symbols: {count}.", count=len(codes)),
        )

        result_items: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for index, code in enumerate(codes):
            code = normalize_code(code)

            def progress_callback(stage: str, message: str, progress: int | None = None) -> None:
                step = max(0.0, min(float(progress or 0), 100.0))
                overall = int(((index + step / 100.0) / total) * 100)
                self.update_task(
                    task_id,
                    now=now,
                    status="running",
                    stage=stage,
                    symbol=code,
                    progress=min(max(overall, 1), 99),
                    message=txt(message, t("{symbol} is being analyzed", symbol=code)),
                )

            self.update_task(
                task_id,
                now=now,
                status="running",
                stage="fetch",
                symbol=code,
                progress=min(max(int((index / total) * 100), 1), 99),
                message=t("Analyzing {symbol} ({index}/{total})", symbol=code, index=index + 1, total=len(codes)),
            )
            result = analyze_stock(
                code,
                cycle,
                enabled_analysts_config=analysis_config_builder(selected),
                selected_model=None,
                progress_callback=progress_callback,
            )
            if not result or not result.get("success"):
                errors.append(
                    {
                        "symbol": code,
                        "message": txt(result.get("error"), t("Analysis failed")) if isinstance(result, dict) else t("Analysis failed"),
                    }
                )
                continue

            stock_info = result.get("stock_info") if isinstance(result.get("stock_info"), dict) else {}
            stock_name = txt(stock_info.get("name"), code)
            indicators = result.get("indicators") if isinstance(result.get("indicators"), dict) else {}
            discussion_result = result.get("discussion_result")
            final_decision = dict_value(result, "final_decision", {})
            agents_results = result.get("agents_results") if isinstance(result.get("agents_results"), dict) else {}
            historical_data = result.get("historical_data") if isinstance(result.get("historical_data"), list) else []

            item = build_payload(
                code=code,
                stock_name=stock_name,
                selected=selected,
                mode=mode,
                cycle=cycle,
                generated_at=txt(result.get("generated_at"), now()),
                stock_info=stock_info,
                indicators=indicators,
                discussion_result=discussion_result,
                final_decision=final_decision,
                agents_results=agents_results,
                historical_data=historical_data,
            )
            item["stockName"] = stock_name
            result_items.append(item)
            self.update_task(
                task_id,
                now=now,
                status="running",
                stage="persist",
                symbol=code,
                progress=min(max(int(((index + 1) / total) * 100), 1), 99),
                message=t("{symbol} analysis completed", symbol=code),
                results=result_items,
                errors=errors,
            )

        if result_items:
            message = t("Analysis completed: success {ok} / {total}", ok=len(result_items), total=len(codes))
            if errors:
                message = t("{base}, failed {failed}", base=message, failed=len(errors))
            self.update_task(
                task_id,
                now=now,
                status="completed",
                stage="completed",
                progress=100,
                message=message,
                results=result_items,
                errors=errors,
                finished_at=now(),
                symbol=txt(result_items[-1].get("symbol"), txt(task.get("symbol"), "")),
            )
        else:
            self.update_task(
                task_id,
                now=now,
                status="failed",
                stage="failed",
                progress=100,
                message=t(
                    "Analysis failed: {reason}",
                    reason="; ".join(txt(item.get("message"), "") for item in errors[:3]) or t("No valid result returned"),
                ),
                errors=errors,
                finished_at=now(),
            )


analysis_task_manager = WorkbenchAnalysisTaskManager()


__all__ = ["WorkbenchAnalysisTaskManager", "analysis_task_manager"]
