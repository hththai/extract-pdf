# Summary

This project aims to extract OCR transaction data from PDF files using OCR technology, and then convert it into a CSV file format for further processing.

# How to use
    Client upload pdf --> Server OCR -->|using in-memory|--> CSV file
    * validate the balance result and return validation with total role as name.
    * No store files on server

# How to run
1. Clone into Dockge or Docker
    git clone \
    cd ocr
2. Create your .env files

    cp .env.example .env
    cp pdf_api/.env.example pdf_api/.env


    API_URL= api dns
    CORS_ORIGINS= dns
    Edit pdf_api/.env and set CORS_ORIGINS to the same IP.
3. Deploy
   1. docker compose up -d --build
4. Update
   git pull
   docker compose up -d --build
