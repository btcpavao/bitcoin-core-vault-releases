    auto* widget=new QWidget; auto* layout=new QVBoxLayout(widget);
    layout->setContentsMargins(0,0,0,0);layout->setSpacing(8);
    const auto plan=m_core->installPlan(m_config);
    const auto error=m_core->validateInstallPlan(m_config);
    QCoreApplication::instance()->setProperty("coreInstallPlanValid",error.isEmpty());
    auto label=[&](const QString& text,const char* name){auto* l=new QLabel(text,widget);l->setObjectName(QString::fromLatin1(name));l->setWordWrap(true);layout->addWidget(l);};
    const QString target=plan.value("target").toString();
    const auto identity=plan.value("expected").toObject();
    label(tr("<b>Installation drive</b><br/>%1 — %2 GiB<br/>%3").arg(identity.value("model").toString().toHtmlEscaped())
        .arg(identity.value("size").toDouble()/(1024.0*1024*1024),0,'f',2).arg(target.toHtmlEscaped()),"coreOfflineReviewCard");
    if(!error.isEmpty()) {label(error.toHtmlEscaped(),"coreOfflineEraseWarning");return widget;}
    const bool erase=plan.value("mode").toString()!=QStringLiteral("advanced");
    const bool efi=plan.value("firmware").toString()==QStringLiteral("efi");
    label(erase ? tr("<b>What will happen</b><br/>Erase every existing partition on this physical disk and create the layout below. Other physical disks are preserved.")
        : efi ? tr("<b>What will happen</b><br/>Format the selected root as ext4. Existing EFI is reused without formatting; a new EFI partition, if shown below, is created as FAT32 in unallocated space. All other existing partitions and physical disks are preserved.")
        : tr("<b>What will happen</b><br/>Format the selected root as ext4. Install the Legacy BIOS bootloader on the selected disk, replacing its previous bootloader in the MBR and boot area. Other data partitions and physical disks are preserved. Other operating systems may need boot menu configuration."),"coreOfflineReviewCard");
    label(efi ? tr("<b>Boot mode:</b> UEFI") : tr("<b>Boot mode:</b> Legacy BIOS"),"coreOfflineReviewCard");
    QString rows=QStringLiteral("<table cellpadding='5'><tr><th align='left'>Partition / size</th><th align='left'>Action</th><th align='left'>Mount</th></tr>");
    for(const auto& value:plan.value("disks").toArray()) {
        const auto disk=value.toObject();if(disk.value("path").toString()!=target) continue;
        for(const auto& entry:disk.value("partitions").toArray()) {
            const auto p=entry.toObject();QString action;
            if(p.value("bios_grub").toBool()) action=p.value("new").toBool()?tr("Create BIOS boot partition; install bootloader"):efi?tr("Keep BIOS boot partition unchanged"):tr("Reuse BIOS boot partition; replace bootloader");
            else if(p.value("extended").toBool()) action=tr("Keep extended partition and its boundaries");
            else if(p.value("mount").toString()==QStringLiteral("/")) action=tr("Format ext4; install Bitcoin Core Vault");
            else if(p.value("mount").toString()==QStringLiteral("/boot/efi")) action=p.value("new").toBool()?tr("Create EFI / FAT32"):tr("Reuse EFI; do not format");
            else if(p.value("mount").toString()==QStringLiteral("/boot")) action=tr("Create and format ext4 boot partition");
            else if(p.value("new").toBool()) action=tr("Create unformatted reservation for %1").arg(CORE_PRODUCT_NODE?tr("Vault"):tr("Node"));
            else action=tr("Keep unchanged");
            QString name=p.value("path").toString();if(name.isEmpty()) name=p.value("original_path").toString();if(name.isEmpty()) name=tr("New partition");
            rows+=QStringLiteral("<tr><td>%1 — %2 GiB</td><td>%3</td><td>%4</td></tr>")
                .arg(name.toHtmlEscaped()).arg(p.value("size").toDouble()/(1024.0*1024*1024),0,'f',2)
                .arg(action.toHtmlEscaped(),p.value("mount").toString().toHtmlEscaped());
        }
    }
    rows+=QStringLiteral("</table>");label(rows,"coreOfflineReviewCard");
    label(erase?tr("All current files on %1 will be permanently erased.").arg(target.toHtmlEscaped()):tr("All current files on the selected root partition will be permanently erased. No existing partition is resized or moved."),"coreOfflineEraseWarning");
    layout->addStretch();return widget;
