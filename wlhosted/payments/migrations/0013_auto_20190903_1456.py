# Generated by Django 2.2.4 on 2019-09-03 12:56

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("payments", "0012_auto_20190102_1658")]

    operations = [
        migrations.AlterField(
            model_name="payment",
            name="recurring",
            field=models.CharField(
                blank=True,
                choices=[
                    ("y", "Annual"),
                    ("b", "Biannual"),
                    ("q", "Quarterly"),
                    ("m", "Monthly"),
                    ("", "Onetime"),
                ],
                default="",
                max_length=10,
            ),
        )
    ]
