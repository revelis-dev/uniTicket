# Generated by Django 4.2.16 on 2024-11-14 10:11

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('uni_ticket', '0024_ticket_uni_ticket__is_clos_8d6d43_idx_and_more'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='ticketassignment',
            name='uni_ticket__taken_b_8d7e69_idx',
        ),
        migrations.RenameIndex(
            model_name='ticket',
            new_name='uni_ticket__is_clos_8d6d43_idx',
            old_name='uni_ticket__is_clos_8d6d44_idx',
        ),
        migrations.RenameIndex(
            model_name='ticket',
            new_name='uni_ticket__priorit_88a7f4_idx',
            old_name='uni_ticket__priorit_88a7f5_idx',
        ),
        migrations.RenameIndex(
            model_name='ticket',
            new_name='uni_ticket__priorit_0066dd_idx',
            old_name='uni_ticket__priorit_0666dd_idx',
        ),
    ]
