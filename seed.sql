-- Учебные данные. Используйте только после schema.sql.
INSERT INTO clients(id, full_name, phone, telegram_id) VALUES
 (1, 'Анна Сергеева', '+79000000001', NULL),
 (2, 'Мария Орлова', '+79000000002', NULL),
 (3, 'Елена Ким', '+79000000003', NULL);
INSERT INTO masters(id, full_name, experience_years, is_active) VALUES
 (1, 'Анна Иванова', 5, TRUE),
 (2, 'Мария Петрова', 3, TRUE),
 (3, 'Ольга Смирнова', 7, TRUE);
INSERT INTO services(id, title, duration_min, price_rub, is_active) VALUES
 (1, 'Классический маникюр', 45, 900),
 (2, 'Маникюр с гель-лаком', 90, 1800),
 (3, 'Снятие покрытия', 30, 350),
 (4, 'Наращивание ногтей', 150, 2900),
 (5, 'Педикюр', 90, 2000),
 (6, 'Коррекция ногтей', 120, 2200);
INSERT INTO master_services(master_id, service_id) VALUES
 (1,1),(1,2),(1,3),(1,4),(1,6),
 (2,1),(2,2),(2,3),(2,5),
 (3,1),(3,2),(3,4),(3,5),(3,6);
INSERT INTO schedules(master_id, weekday, starts_at, ends_at) VALUES
 (1,1,'10:00','19:00'),(1,2,'10:00','19:00'),(1,3,'10:00','19:00'),
 (1,4,'10:00','19:00'),(1,5,'10:00','19:00'),(1,6,'10:00','19:00'),
 (2,1,'11:00','20:00'),(2,2,'11:00','20:00'),(2,3,'11:00','20:00'),
 (2,4,'11:00','20:00'),(2,5,'11:00','20:00'),
 (3,2,'09:00','18:00'),(3,3,'09:00','18:00'),(3,4,'09:00','18:00'),
 (3,5,'09:00','18:00'),(3,6,'09:00','18:00');
-- На ближайший следующий понедельник; START + duration = END.
INSERT INTO bookings(client_id, master_id, service_id, visit_date, starts_at, ends_at,
                     duration_at_booking, price_at_booking, status)
VALUES
 (1, 1, 2, CURRENT_DATE + (8 - EXTRACT(ISODOW FROM CURRENT_DATE)::int),
  '10:00', '11:30', 90, 1800, 'booked'),
 (2, 2, 5, CURRENT_DATE + (8 - EXTRACT(ISODOW FROM CURRENT_DATE)::int),
  '12:00', '13:30', 90, 2000, 'booked');
SELECT setval(pg_get_serial_sequence('clients','id'), (SELECT MAX(id) FROM clients));
SELECT setval(pg_get_serial_sequence('masters','id'), (SELECT MAX(id) FROM masters));
SELECT setval(pg_get_serial_sequence('services','id'), (SELECT MAX(id) FROM services));
SELECT setval(pg_get_serial_sequence('bookings','id'), (SELECT MAX(id) FROM bookings));
