# PE · Prestamo365 CRM DB — справочник таблиц

База: `prod-prestamo365-pe` · сервер: `localhost:55613` (туннель) · пользователь: `viewer` · движок: PostgreSQL 15 (Percona).
Снапшот схемы: 2026-05-05. Полный дамп — рядом в [PE_prestamo365_schema.json](PE_prestamo365_schema.json) (216 таблиц, три схемы: `public`/`handbook`/`logs`).

**Всего таблиц:** 216.

## Подключение из хаба

В `companies.json` для `PE_` указано:
```json
  "crm_db_engine": "postgres",
  "crm_db_name": "prod-prestamo365-pe",
  "crm_db_port": "55613"
```
Хаб поднимает соединение через `pg8000.dbapi.connect(host=localhost, port=55613, user=viewer, database='prod-prestamo365-pe', ...)`.

## Структура схем

- **handbook** — 17 таблиц
- **logs** — 25 таблиц
- **public** — 174 таблиц

## Топ-25 таблиц по числу строк

| Таблица | Строк | Колонок |
|---|---:|---:|
| `public.notification` | 5,201,470 | 26 |
| `public.accrual` | 4,535,175 | 27 |
| `public.user_event` | 4,375,584 | 5 |
| `public.communication` | 4,260,794 | 17 |
| `public.sms` | 3,686,665 | 7 |
| `public.user_change_history` | 2,589,260 | 4 |
| `public.webitel_logs` | 1,971,019 | 7 |
| `public.user_event_trigger` | 1,968,330 | 9 |
| `public.otp` | 1,910,143 | 10 |
| `public.loan_change_history` | 1,515,393 | 4 |
| `public.repayment` | 1,211,474 | 11 |
| `public.session` | 989,145 | 13 |
| `public.admin_notification` | 960,072 | 11 |
| `public.file` | 951,983 | 10 |
| `logs.request_2026_04_27` | 935,443 | 13 |
| `public.application_change_history` | 928,398 | 4 |
| `public.collection_contact_calls` | 928,231 | 22 |
| `logs.request_2026_05_04` | 876,748 | 13 |
| `logs.request_2026_04_30` | 856,260 | 13 |
| `logs.request_2026_04_28` | 825,060 | 13 |
| `logs.request_2026_04_29` | 808,187 | 13 |
| `logs.payments_request` | 659,786 | 13 |
| `public.email` | 594,624 | 9 |
| `public.webitel_call` | 552,663 | 36 |
| `public.abstract_process` | 469,882 | 7 |

## Полный список таблиц по схемам

<details><summary>раскрыть</summary>

### `handbook` (17)

- `bank` — 34 строк, 5 колонок
- `communication_category` — 9 строк, 5 колонок
- `communication_result` — 9 строк, 5 колонок
- `department` — 25 строк, 6 колонок
- `district` — 1,891 строк, 6 колонок
- `education` — 9 строк, 5 колонок
- `email_outbox_addresses` — 6 строк, 6 колонок
- `employment` — 12 строк, 5 колонок
- `employment_industry` — 10 строк, 5 колонок
- `marital_status` — 4 строк, 5 колонок
- `max_penalty_rate` — 0 строк, 6 колонок
- `phone_relation` — 14 строк, 5 колонок
- `phone_source` — 7 строк, 5 колонок
- `phone_type` — 8 строк, 5 колонок
- `province` — 196 строк, 6 колонок
- `sender_name` — -1 строк, 4 колонок
- `ubigeo_index` — 1,891 строк, 5 колонок

### `logs` (25)

- `app_2026_04_27` — 8,441 строк, 5 колонок
- `app_2026_04_28` — 7,901 строк, 5 колонок
- `app_2026_04_29` — 9,327 строк, 5 колонок
- `app_2026_04_30` — 10,327 строк, 5 колонок
- `app_2026_05_01` — 10,018 строк, 5 колонок
- `app_2026_05_02` — 6,347 строк, 5 колонок
- `app_2026_05_03` — 6,861 строк, 5 колонок
- `app_2026_05_04` — 7,965 строк, 5 колонок
- `command_2026_04_27` — 11,237 строк, 8 колонок
- `command_2026_04_28` — 11,414 строк, 8 колонок
- `command_2026_04_29` — 11,314 строк, 8 колонок
- `command_2026_04_30` — 11,385 строк, 8 колонок
- `command_2026_05_01` — 11,331 строк, 8 колонок
- `command_2026_05_02` — 11,429 строк, 8 колонок
- `command_2026_05_03` — 11,164 строк, 8 колонок
- `command_2026_05_04` — 11,178 строк, 8 колонок
- `payments_request` — 659,786 строк, 13 колонок
- `request_2026_04_27` — 935,443 строк, 13 колонок
- `request_2026_04_28` — 825,060 строк, 13 колонок
- `request_2026_04_29` — 808,187 строк, 13 колонок
- `request_2026_04_30` — 856,260 строк, 13 колонок
- `request_2026_05_01` — 403,551 строк, 13 колонок
- `request_2026_05_02` — 316,620 строк, 13 колонок
- `request_2026_05_03` — 264,346 строк, 13 колонок
- `request_2026_05_04` — 876,748 строк, 13 колонок

### `public` (174)

- `abstract_process` — 469,882 строк, 7 колонок
- `accrual` — 4,535,175 строк, 27 колонок
- `admin` — 116 строк, 18 колонок
- `admin_admin_auth_roles` — 319 строк, 2 колонок
- `admin_auth_roles` — 26 строк, 6 колонок
- `admin_authentication_log` — 18,291 строк, 6 колонок
- `admin_notification` — 960,072 строк, 11 колонок
- `affiliate` — 16 строк, 8 колонок
- `affiliate_action` — 17 строк, 11 колонок
- `affiliate_event` — 271,535 строк, 10 колонок
- `agent_notification_campaign` — -1 строк, 10 колонок
- `agreement` — 197,883 строк, 16 колонок
- `api_lead` — 215 строк, 10 колонок
- `api_lead_log` — 2,449 строк, 8 колонок
- `application` — 314,370 строк, 35 колонок
- `application_change_history` — 928,398 строк, 4 колонок
- `application_pending` — 104,273 строк, 13 колонок
- `appsflyer_login` — 86,532 строк, 5 колонок
- `archive_user` — 35,368 строк, 9 колонок
- `auto_assignment` — 8 строк, 5 колонок
- `auto_assignment_time_slots` — 129 строк, 6 колонок
- `auto_debit` — 64,284 строк, 15 колонок
- `auto_debit_campaign` — 1 строк, 14 колонок
- `auto_debit_strategy` — 0 строк, 4 колонок
- `auto_decline_process` — 3,721 строк, 3 колонок
- `aws_rekognition` — 428,010 строк, 6 колонок
- `aws_rekognition_id_card_matches` — 223,182 строк, 5 колонок
- `aws_rekognition_matches` — 146,350 строк, 5 колонок
- `aws_rekognition_selfie_and_id_card_matches` — 187,497 строк, 5 колонок
- `bank_account` — 145,206 строк, 12 колонок
- `bbva_massive_payout` — 140 строк, 4 колонок
- `bbva_massive_payout_money_transfer` — 3,747 строк, 2 колонок
- `bbva_report` — 0 строк, 4 колонок
- `black_list` — 1,831 строк, 13 колонок
- `black_list_pending` — -1 строк, 5 колонок
- `call_center_action_tree` — 256 строк, 12 колонок
- `call_center_action_type` — -1 строк, 6 колонок
- `call_center_call_result` — -1 строк, 6 колонок
- `call_center_client_status` — -1 строк, 6 колонок
- `call_center_result_type` — 43 строк, 6 колонок
- `campaign_audience` — 39 строк, 2 колонок
- `charge` — 184,614 строк, 19 колонок
- `charge_auto_debit` — 63,098 строк, 7 колонок
- `charge_log` — 55,000 строк, 4 колонок
- `collection_agent_goals` — 108 строк, 5 колонок
- `collection_alerts` — 0 строк, 3 колонок
- `collection_alerts_collection_group` — 56 строк, 2 колонок
- `collection_contact_calls` — 928,231 строк, 22 колонок
- `collection_contact_type_values` — 54 строк, 10 колонок
- `collection_contact_types` — 5 строк, 6 колонок
- `collection_contacts` — 8,043 строк, 9 колонок
- `collection_contacts_motivators` — 94,794 строк, 2 колонок
- `collection_contacts_no_payment_reason` — 65,184 строк, 2 колонок
- `collection_external_agency` — 0 строк, 10 колонок
- `collection_external_agency_campaign` — 0 строк, 9 колонок
- `collection_external_agency_log` — 21,233 строк, 11 колонок
- `collection_external_agency_report` — 152 строк, 9 колонок
- `collection_group` — 14 строк, 6 колонок
- `collection_group_admin` — 62 строк, 2 колонок
- `collection_motivators` — 35 строк, 6 колонок
- `collection_no_payment_reason` — 16 строк, 5 колонок
- `collection_score` — 0 строк, 9 колонок
- `collection_strategy` — 64 строк, 6 колонок
- `communication` — 4,260,794 строк, 17 колонок
- `contact` — 25,955 строк, 5 колонок
- `days_statistic` — 156 строк, 20 колонок
- `decision_engine` — 313,230 строк, 7 колонок
- `dialer_campaign` — 35 строк, 12 колонок
- `dialer_process` — 57 строк, 12 колонок
- `discount_campaign_excluded_loans` — 0 строк, 6 колонок
- `discount_campaigns` — 988 строк, 33 колонок
- `discount_offer` — 29,395 строк, 32 колонок
- `discount_offer_input` — 0 строк, 3 колонок
- `document_request` — 23,227 строк, 10 колонок
- `document_request_group` — 13,288 строк, 6 колонок
- `email` — 594,624 строк, 9 колонок
- `email_alpha_names` — -1 строк, 6 колонок
- `employment` — 236,071 строк, 4 колонок
- `extension` — 45,706 строк, 28 колонок
- `file` — 951,983 строк, 10 колонок
- `file_email` — 6,443 строк, 2 колонок
- `firebase_token` — 0 строк, 5 колонок
- `functional_link` — 76,272 строк, 5 колонок
- `functional_link_log` — 77,014 строк, 8 колонок
- `global_settings` — 71 строк, 6 колонок
- `holidays` — 17 строк, 6 колонок
- `import_loan_portfolio` — 0 строк, 6 колонок
- `import_process` — 1 строк, 10 колонок
- `income` — 67,509 строк, 18 колонок
- `kashio_bank_mapping` — -1 строк, 5 колонок
- `kyc_request` — 0 строк, 10 колонок
- `loan` — 83,682 строк, 39 колонок
- `loan_change_history` — 1,515,393 строк, 4 колонок
- `loan_info_sending` — 0 строк, 2 колонок
- `loan_sale` — 0 строк, 9 колонок
- `loans_promo_codes` — 846 строк, 10 колонок
- `loans_promo_codes_discounts` — 349 строк, 7 колонок
- `mailer_inbox_settings` — 3 строк, 6 колонок
- `manual_process` — 10 строк, 3 колонок
- `manual_verification_step` — 0 строк, 4 колонок
- `mass_sending_audience` — 170 строк, 10 колонок
- `mass_sending_campaign` — 154 строк, 12 колонок
- `mass_sending_process` — 23,008 строк, 18 колонок
- `mass_sending_process_users` — 43 строк, 3 колонок
- `messenger_messages` — 104,229 строк, 7 колонок
- `migration_versions` — 639 строк, 3 колонок
- `money_transfer` — 88,423 строк, 16 колонок
- `note` — 155,073 строк, 8 колонок
- `notification` — 5,201,470 строк, 26 колонок
- `nubefact_report` — 66,678 строк, 7 колонок
- `ocr_request` — 434,879 строк, 12 колонок
- `otp` — 1,910,143 строк, 10 колонок
- `overpayment` — 3,707 строк, 7 колонок
- `payment_link_redirection` — 0 строк, 6 колонок
- `payment_provider_log` — 166,433 строк, 11 колонок
- `phone_book` — 332,645 строк, 14 колонок
- `phone_call` — 3,123 строк, 10 колонок
- `phone_call_application_assign` — 5 строк, 6 колонок
- `phone_call_loan_assign` — 320,327 строк, 10 колонок
- `phone_call_user_assign` — 4 строк, 6 колонок
- `popup_settings` — 0 строк, 9 колонок
- `product_config` — 4 строк, 11 колонок
- `profile` — 307,622 строк, 24 колонок
- `promise_to_pay` — 52,971 строк, 14 колонок
- `promo_code` — 0 строк, 11 колонок
- `reclamations` — 262 строк, 22 колонок
- `referral_wallet` — 0 строк, 3 колонок
- `referral_wallet_operation` — 0 строк, 8 колонок
- `registration_flow` — -1 строк, 9 колонок
- `rejection_reason` — 22 строк, 7 колонок
- `related_project` — 0 строк, 6 колонок
- `related_project_application` — 0 строк, 18 колонок
- `repayment` — 1,211,474 строк, 11 колонок
- `report` — 1,831 строк, 12 колонок
- `residence` — 235,964 строк, 7 колонок
- `sat_blacklist` — 0 строк, 22 колонок
- `service_incident` — 0 строк, 8 колонок
- `session` — 989,145 строк, 13 колонок
- `short_link` — 34,863 строк, 8 колонок
- `sls_automatic_process` — 300,588 строк, 9 колонок
- `sls_manual_process` — 77,528 строк, 4 колонок
- `sls_verification_manual_process` — 54,557 строк, 8 колонок
- `sms` — 3,686,665 строк, 7 колонок
- `template` — 282 строк, 9 колонок
- `unsubscribe_email` — 0 строк, 9 колонок
- `user` — 312,544 строк, 33 колонок
- `user_api_data` — 0 строк, 13 колонок
- `user_auto_prolongation_decision_log` — 21,090 строк, 4 колонок
- `user_change_history` — 2,589,260 строк, 4 колонок
- `user_event` — 4,375,584 строк, 5 колонок
- `user_event_notification` — 28 строк, 13 колонок
- `user_event_trigger` — 1,968,330 строк, 9 колонок
- `user_facebook` — 0 строк, 6 колонок
- `user_feedback` — 937 строк, 5 колонок
- `user_notification` — 100,107 строк, 17 колонок
- `user_notification_campaign` — 0 строк, 11 колонок
- `user_notification_process` — 972 строк, 17 колонок
- `user_payment_method` — 15,084 строк, 10 колонок
- `user_settings` — 311,882 строк, 3 колонок
- `user_tags` — 0 строк, 3 колонок
- `user_tags_user` — 0 строк, 2 колонок
- `user_traffic_source` — 104,893 строк, 8 колонок
- `verification_call_request` — 3,905 строк, 5 колонок
- `verification_calls` — 0 строк, 9 колонок
- `wamm_chat_contact` — 678 строк, 10 колонок
- `wamm_chat_contact__loan` — -1 строк, 2 колонок
- `wamm_chat_message` — 1,253 строк, 7 колонок
- `webitel_call` — 552,663 строк, 36 колонок
- `webitel_click_to_call` — 11,046 строк, 11 колонок
- `webitel_loan_verification` — 0 строк, 8 колонок
- `webitel_logs` — 1,971,019 строк, 7 колонок
- `webitel_phone_verification` — 26,839 строк, 11 колонок
- `webitel_queue` — 0 строк, 13 колонок
- `work_schedule` — 27,619 строк, 6 колонок

</details>

## Подробно — ключевые таблицы

### `public.user` — ~312,544 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `affiliate_id` | `integer` | YES |
| `matched_user_id` | `integer` | YES |
| `username` | `character varying` | NO |
| `state` | `character varying` | NO |
| `created_at` | `timestamp with time zone` | NO |
| `confirmed_at` | `timestamp with time zone` | YES |
| `target_url` | `text` | YES |
| `registration_step` | `smallint` | YES |
| `moratorium_till` | `timestamp with time zone` | YES |
| `updated_at` | `timestamp with time zone` | YES |
| `preferred_payment_type` | `character varying` | YES |
| `is_registration_complete` | `boolean` | NO |
| `preferred_product_code` | `character varying` | YES |
| `phone_confirmed_by` | `character varying` | YES |
| `referral_user_id` | `integer` | YES |
| `referral_code` | `character varying` | YES |
| `do_not_disturb` | `boolean` | NO |
| `is_direct_debit_allowed` | `boolean` | NO |
| `is_charge_back_requested` | `boolean` | NO |
| `params` | `jsonb` | YES |
| `ipcountry` | `character varying` | YES |
| `appsflyer_uid` | `character varying` | YES |
| `appsflyer_source_platform` | `character varying` | YES |
| `uuid` | `uuid` | NO |
| `registration_data` | `jsonb` | YES |
| `registered_at` | `timestamp with time zone` | YES |
| `registration_steps_timestamps` | `jsonb` | YES |
| `registered_user_at` | `timestamp with time zone` | YES |
| `has_whats_app_account` | `boolean` | YES |
| `is_loan_auto_prolongation_enabled` | `boolean` | YES |
| `pin_code` | `character varying` | YES |
| `pin_code_fail_attempts_count` | `integer` | YES |

### `public.loan` — ~83,682 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `application_id` | `integer` | NO |
| `collector_id` | `integer` | YES |
| `payment_link_slug` | `character varying` | NO |
| `state` | `character varying` | NO |
| `principal` | `double precision` | NO |
| `tenor` | `smallint` | NO |
| `created_at` | `timestamp with time zone` | NO |
| `disbursed_at` | `timestamp with time zone` | YES |
| `matured_at` | `timestamp with time zone` | YES |
| `closed_at` | `timestamp with time zone` | YES |
| `cancel_reason` | `text` | YES |
| `is_repeat` | `boolean` | YES |
| `is_extension_possible` | `boolean` | YES |
| `is_extended` | `boolean` | NO |
| `ready_for_disbursement` | `boolean` | NO |
| `commission` | `double precision` | YES |
| `last_contact_call_id` | `integer` | YES |
| `last_promise_to_pay_id` | `integer` | YES |
| `external_agency_id` | `integer` | YES |
| `sold_at` | `timestamp with time zone` | YES |
| `external_agency_allocated_to` | `timestamp with time zone` | YES |
| `peerberry_status` | `character varying` | NO |
| `peerberry_error` | `text` | YES |
| `is_direct_debit_registered` | `boolean` | NO |
| `closed_admin_id` | `integer` | YES |
| `rate` | `double precision` | NO |
| `days_past_due` | `integer` | YES |
| `direct_debit_failed_at` | `timestamp with time zone` | YES |
| `uuid` | `uuid` | NO |
| `overpayment_amount` | `numeric` | NO |
| `real_matured_at` | `timestamp with time zone` | YES |
| `collection_group_id` | `integer` | YES |
| `max_days_past_due` | `integer` | YES |
| `requested_tenor` | `smallint` | NO |
| `calculated_total` | `numeric` | NO |
| `thread_id` | `character varying` | YES |
| `thread_id_created_at` | `timestamp with time zone` | YES |

### `public.repayment` — ~1,211,474 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `accrual_id` | `integer` | NO |
| `income_id` | `integer` | NO |
| `uuid` | `uuid` | NO |
| `repaid_accrued_amount` | `numeric` | NO |
| `igv_amount` | `numeric` | NO |
| `total_amount` | `numeric` | NO |
| `executed_at` | `timestamp with time zone` | NO |
| `loan_day` | `integer` | NO |
| `created_at` | `timestamp with time zone` | NO |
| `canceled_total_amount` | `numeric` | YES |

### `public.phone_book` — ~332,645 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `created_by_id` | `integer` | YES |
| `phone_number` | `character varying` | YES |
| `name` | `character varying` | YES |
| `note` | `character varying` | YES |
| `created_at` | `timestamp with time zone` | YES |
| `updated_at` | `timestamp with time zone` | YES |
| `type_id` | `integer` | YES |
| `source_id` | `integer` | YES |
| `relation_id` | `integer` | YES |
| `status` | `character varying` | NO |
| `matched_user_id` | `integer` | YES |
| `weight` | `integer` | YES |

### `public.phone_call` — ~3,123 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `application_id` | `integer` | YES |
| `loan_id` | `integer` | YES |
| `admin_id` | `integer` | YES |
| `created_at` | `timestamp with time zone` | YES |
| `action_tree_id` | `integer` | NO |
| `reminder_date` | `timestamp with time zone` | YES |
| `comment` | `text` | YES |
| `phone_number` | `character varying` | NO |

### `public.wamm_chat_message` — ~1,253 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `loan_id` | `integer` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `message` | `text` | NO |
| `message_id` | `text` | NO |
| `phone` | `character varying` | NO |
| `state` | `character varying` | NO |

### `public.webitel_call` — ~552,663 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | YES |
| `webitel_id` | `character varying` | YES |
| `app_id` | `character varying` | YES |
| `parent_id` | `character varying` | YES |
| `gateway` | `json` | YES |
| `direction` | `character varying` | YES |
| `destination` | `character varying` | YES |
| `from_user` | `json` | YES |
| `to_user` | `json` | YES |
| `variables` | `json` | YES |
| `created` | `timestamp with time zone` | YES |
| `answered` | `timestamp with time zone` | YES |
| `bridged` | `timestamp with time zone` | YES |
| `hangup` | `timestamp with time zone` | YES |
| `hangup_by` | `character varying` | YES |
| `cause` | `character varying` | YES |
| `duration` | `integer` | YES |
| `wait_time` | `integer` | YES |
| `bill_sec` | `integer` | YES |
| `sip_code` | `integer` | YES |
| `files` | `json` | YES |
| `stored` | `timestamp with time zone` | YES |
| `admin_id` | `integer` | YES |
| `extension` | `character varying` | YES |
| `queue` | `json` | YES |
| `queue_id` | `character varying` | YES |
| `queue_name` | `character varying` | YES |
| `talk_sec` | `integer` | YES |
| `from_number` | `character varying` | YES |
| `from_name` | `character varying` | YES |
| `from_type` | `character varying` | YES |
| `to_number` | `character varying` | YES |
| `to_name` | `character varying` | YES |
| `to_type` | `character varying` | YES |
| `record_link` | `character varying` | YES |

### `public.webitel_phone_verification` — ~26,839 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `phone` | `character varying` | NO |
| `params` | `json` | NO |
| `state` | `character varying` | NO |
| `response` | `text` | YES |
| `error` | `text` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `uuid` | `uuid` | NO |
| `update_at` | `timestamp with time zone` | NO |
| `auth_params` | `json` | NO |

### `public.webitel_loan_verification` — ~0 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `application_id` | `integer` | YES |
| `phone` | `character varying` | NO |
| `state` | `character varying` | NO |
| `response` | `text` | YES |
| `error` | `text` | YES |
| `created_at` | `timestamp with time zone` | NO |

### `public.promise_to_pay` — ~52,971 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `loan_id` | `integer` | NO |
| `admin_id` | `integer` | YES |
| `collection_contact_call_id` | `integer` | YES |
| `promise_date` | `timestamp with time zone` | NO |
| `promise_amount` | `numeric` | YES |
| `paid_amount` | `numeric` | YES |
| `status` | `character varying` | NO |
| `completed_at` | `timestamp with time zone` | YES |
| `failed_at` | `timestamp with time zone` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `uuid` | `uuid` | YES |
| `charge_id` | `integer` | YES |

### `public.income` — ~67,509 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `loan_id` | `integer` | NO |
| `gateway` | `character varying` | NO |
| `gateway_transaction_id` | `character varying` | YES |
| `state` | `character varying` | NO |
| `amount` | `double precision` | NO |
| `received_at` | `timestamp with time zone` | NO |
| `processed_at` | `timestamp with time zone` | YES |
| `bank_name` | `character varying` | YES |
| `payment_type` | `character varying` | YES |
| `payment_channel` | `character varying` | YES |
| `last_error_message` | `character varying` | YES |
| `received_from_client_at` | `timestamp with time zone` | YES |
| `created_admin_id` | `integer` | YES |
| `uuid` | `uuid` | NO |
| `not_spent_amount` | `numeric` | NO |
| `canceled_at` | `timestamp with time zone` | YES |

### `public.charge` — ~184,614 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `loan_id` | `integer` | NO |
| `gateway` | `character varying` | NO |
| `state` | `character varying` | NO |
| `status` | `character varying` | NO |
| `params` | `json` | NO |
| `updated_at` | `timestamp with time zone` | NO |
| `finished_at` | `timestamp with time zone` | YES |
| `type` | `character varying` | NO |
| `amount_requested` | `numeric` | NO |
| `amount_confirmed` | `double precision` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `deleted_at` | `timestamp with time zone` | YES |
| `method` | `character varying` | YES |
| `error` | `text` | YES |
| `provider` | `character varying` | YES |
| `uuid` | `uuid` | NO |
| `user_payment_method_id` | `integer` | YES |
| `payment_method_external_id` | `character varying` | YES |

### `public.money_transfer` — ~88,423 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `loan_id` | `integer` | NO |
| `triggered_by_id` | `integer` | YES |
| `gateway` | `character varying` | NO |
| `state` | `character varying` | NO |
| `status` | `character varying` | NO |
| `params` | `json` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `updated_at` | `timestamp with time zone` | NO |
| `scheduled_at` | `timestamp with time zone` | NO |
| `finished_at` | `timestamp with time zone` | YES |
| `error` | `text` | YES |
| `bank_account_id` | `integer` | YES |
| `amount` | `double precision` | YES |
| `transaction_date` | `timestamp with time zone` | YES |
| `uuid` | `uuid` | NO |

## Подсказки для навигации

- **Поиск клиента по телефону:** колонка `public.user.username` хранит основной телефон без префикса страны (Перу — `9XX XXX XXX`). При вызове CRM-эндпоинта по номеру нужно добавить страновой префикс `51`.
- **Активные займы:** `public.loan.state = 'active'`. Полный список статусов: `closed`, `active`, `cancelled`, `pending`. Связь с клиентом — `loan.user_id → user.id`.
- **Платежи / погашения:** `public.repayment` (есть поля по принципу /igv/comm/penalty), связан с `accrual` и `income`. Реально пришедшие переводы — `public.money_transfer`.
- **Дополнительные телефоны:** `public.phone_book` + `handbook.phone_type` (id 1=`main`, 2=`contact_person`, 4=`home`, 5=`other`...).
- **Звонки и WhatsApp:** `public.phone_call`, `public.wamm_chat_message`, `public.webitel_call`, `public.webitel_phone_verification`.
- **Логи** (партиционированы по дням): `logs.app_YYYY_MM_DD`, `logs.command_YYYY_MM_DD`, `logs.request_YYYY_MM_DD`. Для запросов в горизонтальную таблицу обычно достаточно `logs.app` (родительская).
- **Справочники:** `handbook.bank`, `handbook.district`, `handbook.province`, `handbook.communication_result`, `handbook.phone_type` и пр. (всего 17).