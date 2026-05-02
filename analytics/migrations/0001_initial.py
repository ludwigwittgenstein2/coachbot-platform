# Generated manually for MVP
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('bots', '0001_initial'),
        ('conversations', '0001_initial'),
    ]
    operations = [
        migrations.CreateModel(
            name='UsageLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('input_chars', models.IntegerField(default=0)),
                ('output_chars', models.IntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('chatbot', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='bots.chatbot')),
                ('conversation', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='conversations.conversation')),
                ('model', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='bots.ollamamodel')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
