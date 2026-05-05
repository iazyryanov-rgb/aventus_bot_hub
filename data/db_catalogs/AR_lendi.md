# AR · Lendi CRM DB — справочник таблиц

База: `prod_ar_lendi` · сервер: `localhost:55609` (туннель) · пользователь: `viewer` · движок: PostgreSQL 17.
Снапшот схемы: 2026-05-05. Полный дамп — рядом в [AR_lendi_schema.json](AR_lendi_schema.json) (222 таблиц, схемы `public`/`handbook`).

**Всего таблиц:** 222.

## Подключение из хаба

В `companies.json` для `AR_` указано:
```json
  "crm_db_engine": "postgres",
  "crm_db_name": "prod_ar_lendi",
  "crm_db_port": "55609"
```
Хаб поднимает соединение через `pg8000.dbapi.connect(host=localhost, port=55609, user=viewer, database='prod_ar_lendi', ...)`.

## Структура схем

- **handbook** — 13 таблиц
- **public** — 209 таблиц

## Топ-25 таблиц по числу строк

| Таблица | Строк | Колонок |
|---|---:|---:|
| `public.webitel_logs` | 3,421,956 | 7 |
| `public.user_event` | 2,231,791 | 5 |
| `public.scheduled_transaction` | 1,932,923 | 7 |
| `public.notification` | 1,863,274 | 25 |
| `public.communication` | 1,816,627 | 17 |
| `public.user_change_history` | 1,567,589 | 4 |
| `public.sms` | 1,522,753 | 7 |
| `public.user_event_trigger` | 799,453 | 9 |
| `public.executed_transaction` | 712,059 | 19 |
| `public.application_change_history` | 701,663 | 4 |
| `public.user_notification` | 625,839 | 17 |
| `public.user_api_data` | 587,486 | 15 |
| `public.session` | 556,064 | 13 |
| `public.phone_book` | 534,644 | 17 |
| `public.loan_change_history` | 406,451 | 4 |
| `public.file` | 364,878 | 9 |
| `public.email` | 302,910 | 10 |
| `public.aws_rekognition` | 276,312 | 6 |
| `public.collection_contact_calls` | 209,571 | 21 |
| `public.user` | 196,708 | 30 |
| `public.user_last_notification` | 196,194 | 10 |
| `public.profile` | 193,745 | 36 |
| `public.one_time_password` | 193,674 | 5 |
| `public.residence` | 170,728 | 14 |
| `public.employment` | 169,009 | 9 |

## Полный список таблиц по схемам

<details><summary>раскрыть</summary>

### `handbook` (13)

- `bank` — 127 строк, 5 колонок
- `communication_category` — -1 строк, 5 колонок
- `communication_result` — -1 строк, 5 колонок
- `education` — -1 строк, 5 колонок
- `email_outbox_addresses` — -1 строк, 6 колонок
- `employment` — -1 строк, 5 колонок
- `employment_type` — -1 строк, 5 колонок
- `marital_status` — -1 строк, 5 колонок
- `monthly_income` — -1 строк, 5 колонок
- `phone_relation` — -1 строк, 5 колонок
- `phone_source` — -1 строк, 5 колонок
- `phone_type` — -1 строк, 5 колонок
- `resident_type` — -1 строк, 5 колонок

### `public` (209)

- `ab_test_group` — -1 строк, 5 колонок
- `address` — 23,072 строк, 4 колонок
- `admin` — 60 строк, 16 колонок
- `admin_admin_auth_roles` — 183 строк, 2 колонок
- `admin_assigned_audience_rule_admin` — -1 строк, 3 колонок
- `admin_assigned_audience_rule_users` — -1 строк, 4 колонок
- `admin_assigned_audience_rules` — -1 строк, 11 колонок
- `admin_auth_roles` — 18 строк, 6 колонок
- `admin_authentication_log` — 24,872 строк, 6 колонок
- `admin_notification` — 57,087 строк, 11 колонок
- `admin_notification_event` — 16,589 строк, 9 колонок
- `affiliate` — 21 строк, 5 колонок
- `affiliate_action` — 23 строк, 6 колонок
- `affiliate_event` — 139,762 строк, 10 колонок
- `agent_conversation` — 121 строк, 7 колонок
- `agent_conversation_message` — 2,557 строк, 7 колонок
- `agent_notification` — -1 строк, 10 колонок
- `agent_notification_campaign` — -1 строк, 8 колонок
- `agent_notification_process` — -1 строк, 14 колонок
- `agreement` — 57,354 строк, 13 колонок
- `amazon_delivery_report` — -1 строк, 15 колонок
- `application` — 153,365 строк, 39 колонок
- `application_autocreating_campaign` — -1 строк, 10 колонок
- `application_autocreating_process` — -1 строк, 9 колонок
- `application_change_history` — 701,663 строк, 4 колонок
- `application_fields_state` — 155,916 строк, 8 колонок
- `archive_user` — 136 строк, 8 колонок
- `auto_assignment` — -1 строк, 4 колонок
- `auto_debit` — 131,006 строк, 16 колонок
- `auto_debit_campaign` — 7 строк, 17 колонок
- `auto_debit_lyra_request` — 128,867 строк, 11 колонок
- `auto_debit_request` — 131,328 строк, 11 колонок
- `auto_debit_strategy` — -1 строк, 4 колонок
- `auto_debit_strategy_amount` — 3 строк, 4 колонок
- `aventus_decision_engine_data` — 158,231 строк, 16 колонок
- `aws_phone_validation` — -1 строк, 8 колонок
- `aws_rekognition` — 276,312 строк, 6 колонок
- `aws_rekognition_id_card_matches` — 6,527 строк, 5 колонок
- `aws_rekognition_matches` — 5,406 строк, 5 колонок
- `aws_rekognition_selfie_and_id_card_matches` — 137,324 строк, 5 колонок
- `bank_account` — 161,629 строк, 11 колонок
- `bank_account_payment_provider` — -1 строк, 5 колонок
- `bank_account_request` — -1 строк, 10 колонок
- `bank_black_list` — -1 строк, 5 колонок
- `bank_card` — 28,281 строк, 9 колонок
- `bank_card_payment_provider` — 27,542 строк, 6 колонок
- `black_list` — 1,055 строк, 13 колонок
- `call_center_action_tree` — 276 строк, 6 колонок
- `call_center_action_type` — -1 строк, 6 колонок
- `call_center_call_result` — -1 строк, 6 колонок
- `call_center_client_status` — -1 строк, 6 колонок
- `call_center_result_type` — 33 строк, 6 колонок
- `call_file` — -1 строк, 2 колонок
- `campaign_audience` — -1 строк, 2 колонок
- `charge` — 34,799 строк, 18 колонок
- `charge_log` — -1 строк, 4 колонок
- `cm_field` — -1 строк, 3 колонок
- `cm_messages` — -1 строк, 13 колонок
- `cm_profile` — -1 строк, 15 колонок
- `cm_template` — -1 строк, 25 колонок
- `collection_alerts` — -1 строк, 3 колонок
- `collection_alerts_collection_group` — 54 строк, 2 колонок
- `collection_contact_calls` — 209,571 строк, 21 колонок
- `collection_contact_type_values` — 53 строк, 11 колонок
- `collection_contact_types` — -1 строк, 6 колонок
- `collection_contacts` — 11,094 строк, 9 колонок
- `collection_contacts_motivators` — 94,794 строк, 2 колонок
- `collection_contacts_no_payment_reason` — -1 строк, 2 колонок
- `collection_external_agency` — -1 строк, 10 колонок
- `collection_external_agency_campaign` — -1 строк, 10 колонок
- `collection_external_agency_log` — 7,652 строк, 12 колонок
- `collection_external_agency_report` — 979 строк, 9 колонок
- `collection_group` — -1 строк, 6 колонок
- `collection_group_admin` — 231 строк, 2 колонок
- `collection_group_admin_view` — 34 строк, 3 колонок
- `collection_motivators` — 35 строк, 6 колонок
- `collection_no_payment_reason` — -1 строк, 6 колонок
- `collection_score` — -1 строк, 9 колонок
- `commission_settings` — -1 строк, 12 колонок
- `communication` — 1,816,627 строк, 17 колонок
- `contact` — 163,508 строк, 5 колонок
- `country` — 249 строк, 3 колонок
- `db_structure` — -1 строк, 3 колонок
- `default_variables` — -1 строк, 4 колонок
- `device` — -1 строк, 9 колонок
- `device_user` — -1 строк, 4 колонок
- `dialer_campaign` — 24 строк, 13 колонок
- `dialer_process` — 30 строк, 13 колонок
- `discount_campaign_excluded_loans` — 26,423 строк, 6 колонок
- `discount_campaign_notification` — 621 строк, 11 колонок
- `discount_campaigns` — 920 строк, 31 колонок
- `discount_offer` — 43,811 строк, 31 колонок
- `discount_offer_input` — 958 строк, 3 колонок
- `discount_offer_notification_schedule` — 63,781 строк, 7 колонок
- `email` — 302,910 строк, 10 колонок
- `employment` — 169,009 строк, 9 колонок
- `executed_transaction` — 712,059 строк, 19 колонок
- `extension` — 4,300 строк, 17 колонок
- `extension_settings` — -1 строк, 10 колонок
- `favorite_loan` — 96 строк, 4 колонок
- `file` — 364,878 строк, 9 колонок
- `file_email` — 41,283 строк, 2 колонок
- `functional_link` — 43,582 строк, 5 колонок
- `functional_link_log` — 47,530 строк, 8 колонок
- `global_settings` — 77 строк, 6 колонок
- `holidays` — -1 строк, 6 колонок
- `import_loan_portfolio` — -1 строк, 6 колонок
- `import_process` — 13 строк, 11 колонок
- `income` — 27,580 строк, 18 колонок
- `income_log` — 55,013 строк, 6 колонок
- `invoice` — 36,289 строк, 11 колонок
- `invoice_item` — 46,047 строк, 6 колонок
- `invoice_number` — -1 строк, 11 колонок
- `kyc_request` — -1 строк, 10 колонок
- `landing_leads` — -1 строк, 9 колонок
- `lead` — -1 строк, 7 колонок
- `loan` — 40,080 строк, 40 колонок
- `loan_anomaly_notification` — -1 строк, 12 колонок
- `loan_change_history` — 406,451 строк, 4 колонок
- `loan_header_rule` — -1 строк, 12 колонок
- `loan_info_sending` — -1 строк, 2 колонок
- `loan_rate_rule` — -1 строк, 13 колонок
- `loan_sale` — -1 строк, 14 колонок
- `loan_term_rule` — -1 строк, 13 колонок
- `mailer_inbox_settings` — 6 строк, 6 колонок
- `manual_verification_step` — 28,092 строк, 4 колонок
- `mass_sending_audience` — 160 строк, 10 колонок
- `mass_sending_campaign` — 219 строк, 16 колонок
- `mass_sending_process` — 21,851 строк, 25 колонок
- `mass_sending_process_users` — 15 строк, 3 колонок
- `messenger_messages` — 105,202 строк, 7 колонок
- `migration_versions` — 565 строк, 3 колонок
- `money_transfer` — 41,476 строк, 19 колонок
- `note` — 135,137 строк, 8 колонок
- `notification` — 1,863,274 строк, 25 колонок
- `notification_file` — 37,534 строк, 2 колонок
- `ocr_request` — 163,193 строк, 12 колонок
- `one_time_password` — 193,674 строк, 5 колонок
- `payment_link_redirection` — -1 строк, 6 колонок
- `payment_provider_log` — -1 строк, 9 колонок
- `phone_book` — 534,644 строк, 17 колонок
- `phone_call` — 19,021 строк, 13 колонок
- `phone_call_application_assign` — 5,591 строк, 6 колонок
- `phone_call_loan_assign` — 88,464 строк, 10 колонок
- `phone_call_user_assign` — 1,028 строк, 6 колонок
- `popup_settings` — -1 строк, 10 колонок
- `popup_user_showing` — 104,329 строк, 4 колонок
- `product` — -1 строк, 56 колонок
- `product_commission_strategy` — -1 строк, 2 колонок
- `product_commission_strategy_settings` — -1 строк, 8 колонок
- `product_extension_payment_strategy` — -1 строк, 9 колонок
- `product_payment_commission_strategy` — -1 строк, 5 колонок
- `product_pdi_rate_strategy` — -1 строк, 2 колонок
- `product_pdi_rate_strategy_settings` — -1 строк, 5 колонок
- `product_rate_strategy` — -1 строк, 2 колонок
- `product_rate_strategy_settings` — -1 строк, 5 колонок
- `product_setting` — -1 строк, 23 колонок
- `profile` — 193,745 строк, 36 колонок
- `promise_to_pay` — 20,924 строк, 12 колонок
- `promo_code` — -1 строк, 10 колонок
- `push_token` — -1 строк, 9 колонок
- `rcs_template` — -1 строк, 9 колонок
- `referral_wallet` — -1 строк, 3 колонок
- `referral_wallet_operation` — -1 строк, 8 колонок
- `rejection_reason` — -1 строк, 7 колонок
- `related_project` — -1 строк, 11 колонок
- `related_project_application` — -1 строк, 20 колонок
- `related_project_loan` — -1 строк, 15 колонок
- `report` — 24,394 строк, 13 колонок
- `residence` — 170,728 строк, 14 колонок
- `sat_blacklist` — -1 строк, 23 колонок
- `scheduled_transaction` — 1,932,923 строк, 7 колонок
- `service_incident` — -1 строк, 8 колонок
- `session` — 556,064 строк, 13 колонок
- `short_link` — -1 строк, 7 колонок
- `sms` — 1,522,753 строк, 7 колонок
- `template` — 324 строк, 11 колонок
- `unsubscribe_email` — -1 строк, 9 колонок
- `user` — 196,708 строк, 30 колонок
- `user_api_data` — 587,486 строк, 15 колонок
- `user_change_history` — 1,567,589 строк, 4 колонок
- `user_document` — 159,908 строк, 8 колонок
- `user_event` — 2,231,791 строк, 5 колонок
- `user_event_notification` — -1 строк, 15 колонок
- `user_event_trigger` — 799,453 строк, 9 колонок
- `user_facebook` — -1 строк, 6 колонок
- `user_last_notification` — 196,194 строк, 10 колонок
- `user_notification` — 625,839 строк, 17 колонок
- `user_notification_campaign` — 12 строк, 11 колонок
- `user_notification_process` — 1,715 строк, 17 колонок
- `user_payment_provider` — 24,209 строк, 6 колонок
- `user_tags` — -1 строк, 3 колонок
- `user_tags_user` — -1 строк, 2 колонок
- `user_tags_user_log` — -1 строк, 7 колонок
- `user_wallet` — 20,635 строк, 6 колонок
- `verification_calls` — -1 строк, 9 колонок
- `warning` — 6,699 строк, 5 колонок
- `wazzup_channels` — -1 строк, 9 колонок
- `wazzup_messages` — -1 строк, 28 колонок
- `webitel_call` — -1 строк, 32 колонок
- `webitel_call_upload_queue` — -1 строк, 7 колонок
- `webitel_click_to_call` — 89,989 строк, 11 колонок
- `webitel_invalid_calls` — -1 строк, 6 колонок
- `webitel_loan_verification` — -1 строк, 8 колонок
- `webitel_logs` — 3,421,956 строк, 7 колонок
- `webitel_phone_verification` — 20,314 строк, 9 колонок
- `webitel_queue` — -1 строк, 13 колонок
- `webitel_user` — -1 строк, 8 колонок
- `work_schedule` — 10,806 строк, 6 колонок

</details>

## Подробно — ключевые таблицы

### `public.user` — ~196,708 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `affiliate_id` | `integer` | YES |
| `matched_user_id` | `integer` | YES |
| `username` | `character varying` | NO |
| `password_hash` | `character varying` | NO |
| `state` | `character varying` | NO |
| `created_at` | `timestamp with time zone` | NO |
| `confirmation_code` | `character varying` | YES |
| `confirmed_at` | `timestamp with time zone` | YES |
| `target_url` | `text` | YES |
| `registration_step` | `smallint` | YES |
| `moratorium_till` | `timestamp with time zone` | YES |
| `updated_at` | `timestamp with time zone` | YES |
| `preferred_payment_type` | `character varying` | YES |
| `is_registration_complete` | `boolean` | NO |
| `credit_bureau_confirmation_code` | `character varying` | YES |
| `credit_bureau_confirmed_at` | `timestamp with time zone` | YES |
| `preferred_product_code` | `character varying` | NO |
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
| `reason_not_auto_merging` | `character varying` | YES |
| `is_test_client` | `boolean` | NO |

### `public.loan` — ~40,080 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `application_id` | `integer` | NO |
| `product_id` | `integer` | NO |
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
| `is_extension_requested` | `boolean` | NO |
| `is_extended` | `boolean` | NO |
| `extension_requested_at` | `timestamp with time zone` | YES |
| `ready_for_disbursement` | `boolean` | NO |
| `commission` | `double precision` | YES |
| `last_contact_call_id` | `integer` | YES |
| `last_promise_to_pay_id` | `integer` | YES |
| `external_agency_id` | `integer` | YES |
| `sold_at` | `timestamp with time zone` | YES |
| `external_agency_allocated_to` | `timestamp with time zone` | YES |
| `peerberry_status` | `character varying` | NO |
| `peerberry_error` | `text` | YES |
| `promo_code_id` | `integer` | YES |
| `closed_admin_id` | `integer` | YES |
| `rate` | `double precision` | NO |
| `days_past_due` | `integer` | YES |
| `direct_debit_failed_at` | `timestamp with time zone` | YES |
| `max_days_past_due` | `integer` | YES |
| `collection_group_id` | `integer` | YES |
| `sold_company_id` | `integer` | YES |
| `is_additional_rate_for_past_due_added` | `boolean` | NO |
| `is_charge_back_requested` | `boolean` | NO |
| `is_manually_activated` | `boolean` | NO |
| `loan_number` | `integer` | YES |

### `public.phone_book` — ~534,644 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `created_by_id` | `integer` | YES |
| `value` | `character varying` | YES |
| `name` | `character varying` | YES |
| `note` | `character varying` | YES |
| `created_at` | `timestamp with time zone` | YES |
| `updated_at` | `timestamp with time zone` | YES |
| `type_id` | `integer` | YES |
| `source_id` | `integer` | YES |
| `relation_id` | `integer` | YES |
| `status` | `character varying` | NO |
| `validation_state` | `character varying` | YES |
| `matched_user_id` | `integer` | YES |
| `weight` | `integer` | YES |
| `updated_by_id` | `integer` | YES |
| `category` | `character varying` | NO |

### `public.phone_call` — ~19,021 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `application_id` | `integer` | YES |
| `loan_id` | `integer` | YES |
| `admin_id` | `integer` | YES |
| `phone_number` | `character varying` | NO |
| `created_at` | `timestamp with time zone` | NO |
| `call_center_action_type_id` | `integer` | NO |
| `call_center_client_status_id` | `integer` | NO |
| `call_center_call_result_id` | `integer` | NO |
| `call_center_result_type_id` | `integer` | NO |
| `reminder_date` | `timestamp with time zone` | YES |
| `comment` | `text` | YES |

### `public.webitel_call` — ~-1 строк

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
| `wait_sec` | `integer` | YES |
| `bill_sec` | `integer` | YES |
| `sip_code` | `integer` | YES |
| `files` | `json` | YES |
| `stored` | `timestamp with time zone` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `admin_id` | `integer` | YES |
| `extension` | `character varying` | YES |
| `queue` | `json` | YES |
| `queue_id` | `character varying` | YES |
| `queue_name` | `character varying` | YES |
| `webitel_user_id` | `integer` | YES |
| `agent_id` | `integer` | YES |
| `talk_sec` | `integer` | YES |

### `public.webitel_phone_verification` — ~20,314 строк

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
| `code` | `character varying` | YES |

### `public.income` — ~27,580 строк

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
| `bank_sender_name` | `character varying` | YES |
| `payment_type` | `character varying` | YES |
| `payment_channel` | `character varying` | YES |
| `last_error_message` | `character varying` | YES |
| `received_from_client_at` | `timestamp with time zone` | YES |
| `created_admin_id` | `integer` | YES |
| `bank_receiver_name` | `character varying` | YES |
| `charge_id` | `integer` | YES |
| `allow_user_events` | `boolean` | NO |

### `public.charge` — ~34,799 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `loan_id` | `integer` | NO |
| `gateway` | `character varying` | NO |
| `state` | `character varying` | NO |
| `status` | `character varying` | NO |
| `params` | `json` | NO |
| `updated_at` | `timestamp with time zone` | YES |
| `finished_at` | `timestamp with time zone` | YES |
| `type` | `character varying` | NO |
| `tenor` | `integer` | NO |
| `amount_requested` | `double precision` | NO |
| `amount_confirmed` | `double precision` | YES |
| `created_at` | `timestamp with time zone` | NO |
| `deleted_at` | `timestamp with time zone` | YES |
| `method` | `character varying` | YES |
| `error` | `text` | YES |
| `provider` | `character varying` | YES |
| `need_adding_payment_commission` | `boolean` | NO |

### `public.promise_to_pay` — ~20,924 строк

| Колонка | Тип | Nullable |
|---|---|---|
| `id` | `integer` | NO |
| `user_id` | `integer` | NO |
| `loan_id` | `integer` | NO |
| `admin_id` | `integer` | YES |
| `collection_contact_call_id` | `integer` | YES |
| `promise_date` | `timestamp with time zone` | NO |
| `promise_amount` | `double precision` | YES |
| `paid_amount` | `double precision` | YES |
| `status` | `character varying` | NO |
| `completed_at` | `timestamp with time zone` | YES |
| `failed_at` | `timestamp with time zone` | YES |
| `created_at` | `timestamp with time zone` | NO |

### `public.money_transfer` — ~41,476 строк

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
| `bank_card_id` | `integer` | YES |
| `bank_account_id` | `integer` | YES |
| `amount` | `double precision` | YES |
| `transaction_date` | `timestamp with time zone` | YES |
| `request` | `json` | YES |
| `response` | `json` | YES |
| `type` | `character varying` | NO |

## Подсказки для навигации

- **Поиск клиента по телефону:** `public.user.username` хранит уже полностью международный номер (для Аргентины — `549...`, 13 цифр). Префикс страны добавлять не нужно.
- **Активные займы:** `public.loan.state = 'active'`. Возможные значения `state`: `closed`, `active`, `defaulted`, `cancelled`, `transfer_fail`. Связь с клиентом — `loan.user_id → user.id`.
- **Платежи:** `public.repayment` (если есть) и `public.income` / `public.income_log`. `public.payment_link_redirection` — переходы по ссылке на оплату.
- **Дополнительные телефоны:** `public.phone_book` + `handbook.phone_type` — справочник типов (Main / Contact / Home / ...).
- **Звонки и WhatsApp:** `public.phone_call`, `public.webitel_call`, `public.webitel_phone_verification`.
- Схема почти полностью совпадает с PE Prestamo365 (Aventus-движок). Большая часть SQL переиспользуется, кроме страновых нюансов и имени БД.