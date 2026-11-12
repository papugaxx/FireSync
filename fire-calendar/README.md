# FireSync

Harmonized MODIS + VIIRS burning activity calendar. NASA Space Apps Challenge 2026.

## Запуск

```bash
npm install
npm run dev
```

- `http://localhost:3000` — лендинг
- `http://localhost:3000/explore` — прототип календаря (пока на тестовых данных)

## Подключение бэкенда

Скопируй `.env.example` в `.env.local` и укажи адрес Django:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Пока переменная пустая, `./lib/api.ts` отдаёт моки из `lib/mock.ts`.
Форматы ответов описаны в `./types/api.ts`.

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
