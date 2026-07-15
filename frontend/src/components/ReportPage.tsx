import React, { useState } from 'react';
import { useKeycloak } from '@react-keycloak/web';

interface ReportRow {
  external_user_id: string;
  full_name: string;
  prosthetic_model: string;
  prosthetic_serial: string;
  report_date: string;
  movements_count: number;
  avg_signal_value: number;
  max_signal_value: number;
  min_signal_value: number;
  avg_response_time_ms: number;
  usage_minutes: number;
}

interface ReportResponse {
  user_id: string;
  period_from: string;
  period_to: string;
  count: number;
  reports: ReportRow[];
}

const ReportPage: React.FC = () => {
  const { keycloak, initialized } = useKeycloak();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [periodFrom, setPeriodFrom] = useState<string>('');
  const [periodTo, setPeriodTo] = useState<string>('');

  const downloadReport = async () => {
    if (!keycloak?.authenticated) {
      setError('Необходимо авторизоваться');
      return;
    }

    try {
      setLoading(true);
      setError(null);
      setReport(null);

      // Обновляем токен, если он скоро истечёт
      await keycloak.updateToken(30);

      const params = new URLSearchParams();
      if (periodFrom) params.append('period_from', periodFrom);
      if (periodTo) params.append('period_to', periodTo);

      const query = params.toString();
      const url = `${process.env.REACT_APP_API_URL}/reports${query ? `?${query}` : ''}`;
      const response = await fetch(url, {
        headers: {
          Authorization: `Bearer ${keycloak.token}`,
        },
      });

      if (response.status === 401) {
        throw new Error('Ошибка аутентификации. Пожалуйста, войдите снова.');
      }
      if (response.status === 403) {
        throw new Error('Доступ запрещён. Вы можете запрашивать только собственный отчёт.');
      }
      if (!response.ok) {
        const body = await response.text();
        throw new Error(`Ошибка сервера: ${response.status} ${body}`);
      }

      const data: ReportResponse = await response.json();
      setReport(data);

      // Также предлагаем скачать отчёт как JSON-файл
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const downloadUrl = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = downloadUrl;
      a.download = `report_${data.user_id}_${data.period_from}_${data.period_to}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(downloadUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Произошла ошибка');
    } finally {
      setLoading(false);
    }
  };

  if (!initialized) {
    return <div className="flex items-center justify-center min-h-screen">Loading...</div>;
  }

  if (!keycloak.authenticated) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100">
        <button
          onClick={() => keycloak.login()}
          className="px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600"
        >
          Войти
        </button>
      </div>
    );
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-screen bg-gray-100 p-4">
      <div className="w-full max-w-4xl p-8 bg-white rounded-lg shadow-md">
        <h1 className="text-2xl font-bold mb-6">Отчёт о работе протеза</h1>

        <div className="flex flex-col sm:flex-row gap-4 mb-6">
          <div className="flex flex-col">
            <label htmlFor="period-from" className="text-sm text-gray-600 mb-1">
              С
            </label>
            <input
              id="period-from"
              type="date"
              value={periodFrom}
              onChange={(e) => setPeriodFrom(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2"
            />
          </div>
          <div className="flex flex-col">
            <label htmlFor="period-to" className="text-sm text-gray-600 mb-1">
              По
            </label>
            <input
              id="period-to"
              type="date"
              value={periodTo}
              onChange={(e) => setPeriodTo(e.target.value)}
              className="border border-gray-300 rounded px-3 py-2"
            />
          </div>
          <div className="flex items-end">
            <button
              onClick={downloadReport}
              disabled={loading}
              className={`px-4 py-2 bg-blue-500 text-white rounded hover:bg-blue-600 ${
                loading ? 'opacity-50 cursor-not-allowed' : ''
              }`}
            >
              {loading ? 'Загрузка отчёта...' : 'Получить отчёт'}
            </button>
          </div>
        </div>

        {error && (
          <div className="mb-4 p-4 bg-red-100 text-red-700 rounded">{error}</div>
        )}

        {report && (
          <div className="mt-4">
            <h2 className="text-lg font-semibold mb-2">
              Результат ({report.count} записей за период {report.period_from} — {report.period_to})
            </h2>
            {report.count === 0 ? (
              <p className="text-gray-600">Нет данных за выбранный период.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full text-sm border">
                  <thead className="bg-gray-50">
                    <tr>
                      <th className="border px-2 py-1">Дата</th>
                      <th className="border px-2 py-1">Модель</th>
                      <th className="border px-2 py-1">Серийный номер</th>
                      <th className="border px-2 py-1">Движения</th>
                      <th className="border px-2 py-1">Средний сигнал</th>
                      <th className="border px-2 py-1">Макс. сигнал</th>
                      <th className="border px-2 py-1">Мин. сигнал</th>
                      <th className="border px-2 py-1">Среднее время отклика, мс</th>
                      <th className="border px-2 py-1">Минут использования</th>
                    </tr>
                  </thead>
                  <tbody>
                    {report.reports.map((row, idx) => (
                      <tr key={idx} className="odd:bg-white even:bg-gray-50">
                        <td className="border px-2 py-1">{row.report_date}</td>
                        <td className="border px-2 py-1">{row.prosthetic_model}</td>
                        <td className="border px-2 py-1">{row.prosthetic_serial}</td>
                        <td className="border px-2 py-1">{row.movements_count}</td>
                        <td className="border px-2 py-1">{row.avg_signal_value.toFixed(3)}</td>
                        <td className="border px-2 py-1">{row.max_signal_value.toFixed(3)}</td>
                        <td className="border px-2 py-1">{row.min_signal_value.toFixed(3)}</td>
                        <td className="border px-2 py-1">{row.avg_response_time_ms.toFixed(1)}</td>
                        <td className="border px-2 py-1">{row.usage_minutes}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ReportPage;
