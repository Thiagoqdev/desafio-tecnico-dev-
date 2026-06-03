'''Views for the indices module.

POST /indices/importar/  — starts a background import task.
GET  /indices/importar/  — returns current import progress or status.
'''

import json
import threading
from datetime import date

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import JsonResponse
from django.views.generic import View

from .models import IndexType
from .services import (
    IndexService,
    clear_import_progress,
    get_import_lock,
    get_import_progress,
    normalize_reference_date,
    set_import_progress,
)


class ImportIndicesView(LoginRequiredMixin, View):
    '''AJAX endpoint that fetches and stores all index values.

    POST triggers the import in a background thread and returns immediately.
    GET returns current progress or stored-value counts.
    '''

    MIN_DATE = date(1990, 1, 1)

    def get(self, request):
        progress = get_import_progress(request.user.pk)

        if progress and progress.get('running'):
            return JsonResponse({
                'ok': True,
                'running': True,
                'processed': progress.get('processed', 0),
                'total': progress.get('total', 0),
                'created': progress.get('created', 0),
                'skipped': progress.get('skipped', 0),
                'errors': progress.get('errors', 0),
                'percent': progress.get('percent', 0),
            })

        service = IndexService()
        status = service.get_status()
        for code in IndexService.CODES:
            status.setdefault(code, 0)
        return JsonResponse({'ok': True, 'running': False, 'status': status})

    def post(self, request):
        user_id = request.user.pk
        lock = get_import_lock(user_id)

        if not lock.acquire(blocking=False):
            return JsonResponse(
                {'ok': False, 'error': 'Importação já está em andamento.'},
                status=409,
            )
        lock.release()

        progress = get_import_progress(user_id)
        if progress and progress.get('running'):
            return JsonResponse(
                {'ok': False, 'error': 'Importação já está em progresso.'},
                status=409,
            )

        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, TypeError):
            body = {}

        start_str = body.get('start', '1990-01')
        end_str = body.get('end', date.today().strftime('%Y-%m'))

        try:
            start = date.fromisoformat(start_str + '-01')
            end = date.fromisoformat(end_str + '-01')
        except (ValueError, TypeError):
            return JsonResponse({'ok': False, 'error': 'Datas inválidas.'}, status=400)

        if start < self.MIN_DATE:
            start = self.MIN_DATE
        if end > date.today():
            end = normalize_reference_date(date.today())

        total_months = (end.year - start.year) * 12 + (end.month - start.month) + 1
        total = total_months * len(IndexService.CODES)

        set_import_progress(user_id, {
            'running': True,
            'processed': 0,
            'total': total,
            'created': 0,
            'skipped': 0,
            'errors': 0,
            'percent': 0,
        })

        thread = threading.Thread(
            target=self._run_import,
            args=(user_id, start, end),
            daemon=True,
        )
        thread.start()

        return JsonResponse({
            'ok': True,
            'running': True,
            'total': total,
        })

    @staticmethod
    def _run_import(user_id, start, end):
        service = IndexService()

        def on_progress(processed, total, created, skipped, errors):
            percent = int((processed / total) * 100) if total > 0 else 0
            set_import_progress(user_id, {
                'running': True,
                'processed': processed,
                'total': total,
                'created': created,
                'skipped': skipped,
                'errors': errors,
                'percent': percent,
            })

        try:
            result = service.bulk_import(start, end, progress_callback=on_progress)
        except Exception as exc:
            progress = get_import_progress(user_id) or {}
            progress.update({
                'running': False,
                'error': str(exc),
            })
            set_import_progress(user_id, progress)
            return

        progress = get_import_progress(user_id) or {}
        progress.update({
            'running': False,
            'result': result,
        })
        set_import_progress(user_id, progress)