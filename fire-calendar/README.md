# FireSync

Harmonized MODIS + VIIRS burning activity calendar. NASA Space Apps Challenge 2026.

## Запуск

Проще всего — всё сразу (бэкенд + сайт) из корня репозитория:

```bash
python3 run.py          # Windows: py run.py
```

Только сайт:

```bash
cp .env.example .env.local     # адрес бэкенда: NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
npm install
npm run dev
```

- `http://localhost:3000` — лендинг
- `http://localhost:3000/explore` — календарь на настоящих данных NASA FIRMS

## Подключение бэкенда

Бэкенд — FastAPI (`../backend`), адреса `/api/...` описаны в `../backend/frontend_api.py`,
форматы ответов — в `./types/api.ts`. Адрес задаёт `NEXT_PUBLIC_API_URL`.
Если переменная пустая, `./lib/api.ts` отдаёт демо-данные из `lib/mock.ts`.

Для сервера адрес вшивается при сборке: `NEXT_PUBLIC_API_URL=https://ваш-домен npm run build`
(см. `../backend/deploy/setup_server.sh`).

## Структура

```
./
app/
    page.tsx              лендинг (секции: hero, problem, how, features, team, cta)
    explore/page.tsx      страница календаря
  components/
    ui/index.tsx          базовые элементы: Section, Card, Button, Select, Stat, Placeholder
    layout/               Header, Footer
    explore/              Explorer (логика страницы), YearCalendar, DayStrip,
                          MonthlyChart, FireMap, легенды
  lib/
    api.ts                запросы к API / моки, CSV-экспорт
    useApi.ts             хук загрузки данных
    mock.ts               тестовые данные
    colors.ts             цветовые шкалы для данных (календарь, карта)
  types/api.ts            типы ответов API
```

## Как натянуть дизайн

Стилей сейчас нет, только раскладка и рамки-заглушки.

1. Цвета и шрифты: `./app/globals.css`, блок `@theme`.
2. Кнопки, карточки, поля: `./components/ui/index.tsx`. Их используют все страницы.
3. Шапка и подвал: `./components/layout/`.
4. Цвета данных (тепловая шкала, MODIS/VIIRS): `./lib/colors.ts`.
5. Места с пометкой `TODO` в коде ждут контент из дизайна (логотип, картинка в hero, команда).
