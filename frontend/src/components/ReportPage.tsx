import React, { useEffect, useState } from 'react';
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

interface AvailabilityResponse {
  user_id: string;
  min_date: string | null;
  max_date: string | null;
  has_data: boolean;
}

const ReportPage: React.FC = () => {
  const { keycloak, initialized } = useKeycloak();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);
  const [periodFrom, setPeriodFrom] = useState<string>('');
  const [periodTo, setPeriodTo] = useState<string>('');
  const [availability, setAvailability] = useState<AvailabilityResponse | null>(null);
  const [availabilityLoading, setAvailabilityLoading] = useState(false);

  const apiUrl = process.env.REACT_APP_API_URL;

  // Загружаем доступный диапазон дат из OLAP при входе пользователя
  useEffect(() => {
    if (!keycloak?.authenticated || !apiUrl) {
      setAvailability(null);
      return;
    }

    const loadAvailability = async () => {
      try {
        setAvailabilityLoading(true);

        if (!keycloak.token) {
          setAvailability(null);
          return;
        }

        const response = await fetch(`${apiUrl}/reports/availability`, {
          headers: {
            Authorization: `Bearer ${keycloak.token}`,
          },
        });

        if (!response.ok) {
          // Не показываем ошибку пользователю — это вспомогательный запрос
          setAvailability(null);
          return;
        }

        const data: AvailabilityResponse = await response.json();
        setAvailability(data);

        // Автоматически подставляем рекомендуемый период, если поля пустые
        if (data.has_data && data.min_date && data.max_date) {
          setPeriodFrom((prev) => prev || data.min_date!);
          setPeriodTo((prev) => prev || data.max_date!);
        }
      } catch {
        setAvailability(null);
      } finally {
        setAvailabilityLoading(false);
      }
    };

    loadAvailability();
  }, [keycloak, keycloak?.authenticated, apiUrl]);

  const fetchReports = async (attemptRefresh = true): Promise<ReportResponse> => {
    if (!keycloak?.authenticated || !apiUrl) {
      throw new Error('Необходимо авторизоваться');
    }

    const params = new URLSearchParams();
    if (periodFrom) params.append('period_from', periodFrom);
    if (periodTo) params.append('period_to', periodTo);

    const query = params.toString();
    const url = `${apiUrl}/reports${query ? `?${query}` : ''}`;

    // eslint-disable-next-line no-console
    console.log('[ReportPage] fetching', url, 'token present:', !!keycloak.token);

    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${keycloak.token ?? ''}`,
      },
    });

    // eslint-disable-next-line no-console
    console.log('[ReportPage] response status', response.status);

    if (response.status === 401 && attemptRefresh) {
      // eslint-disable-next-line no-console
      console.log('[ReportPage] got 401, trying to refresh token');
      const refreshed = await keycloak.updateToken(30);
      // eslint-disable-next-line no-console
      console.log('[ReportPage] token refreshed:', refreshed);
      return fetchReports(false);
    }

    if (response.status === 401) {
      throw new Error('Ошибка аутентификации. Пожалуйста, войдите снова.');
    }
    if (response.status === 403) {
      throw new Error('Доступ запрещён. Вы можете запрашивать только собственный отчёт.');
    }
    if (!response.ok) {
      let detail = '';
      try {
        const err = await response.json();
        detail = err.detail ? `: ${err.detail}` : '';
      } catch {
        detail = `: ${await response.text()}`;
      }
      throw new Error(`Ошибка сервера ${response.status}${detail}`);
    }

    return response.json();
  };

  const downloadReport = async () => {
    try {
      setLoading(true);
      setError(null);
      setReport(null);

      const data = await fetchReports();
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
      // eslint-disable-next-line no-console
      console.error('[ReportPage] downloadReport error:', err);
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

        <div className="mb-6 p-4 bg-blue-50 text-blue-800 rounded text-sm">
          <p className="font-semibold mb-1">Как формируется отчёт</p>
          <p>
            Каждую ночь в 03:00 Airflow забирает сырые данные телеметрии из PostgreSQL,
            агрегирует их и записывает в ClickHouse (OLAP). Кнопка «Получить отчёт»
            только читает уже подготовленные данные из OLAP — сам Airflow при этом не
            запускается.
          </p>
          <p className="mt-2">
            Если за выбранный период нет данных, значит он ещё не обработан. Обычно
            данные появляются на следующий день после их появления в источнике.
          </p>
        </div>

        {availability?.has_data && (
          <div className="mb-6 p-3 bg-green-50 text-green-800 rounded text-sm">
            <span className="font-semibold">Доступные даты в OLAP: </span>
            {availability.min_date} — {availability.max_date}
          </div>
        )}

        {availability && !availability.has_data && !availabilityLoading && (
          <div className="mb-6 p-3 bg-yellow-50 text-yellow-800 rounded text-sm">
            В витрине OLAP пока нет данных. Подождите, пока Airflow выполнит расчёт
            (запускается ежедневно в 03:00), или обратитесь к администратору.
          </div>
        )}

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
              <div className="text-gray-600">
                <p>Нет данных за выбранный период.</p>
                <p className="mt-2 text-sm">
                  Возможная причина: этот период ещё не обработан Airflow. Данные
                  попадают в отчёт только после ночного расчёта (03:00 за предыдущий
                  день).
                </p>
              </div>
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
