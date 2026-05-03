web: python manage.py migrate && python manage.py seed_bots && python manage.py collectstatic --noinput && gunicorn coachbot_project.wsgi --bind 0.0.0.0:$PORT
web: gunicorn coachbot_project.wsgi --log-file -
