    auto* widget=new QWidget; auto* layout=new QVBoxLayout(widget);
    layout->setContentsMargins(0,0,0,0);layout->setSpacing(8);
    const auto plan=m_core->installPlan(m_config);
    const auto error=m_core->validateInstallPlan(m_config);
    QCoreApplication::instance()->setProperty("coreInstallPlanValid",error.isEmpty());
    auto label=[&](const QString& text,const char* name){auto* l=new QLabel(text,widget);l->setObjectName(QString::fromLatin1(name));l->setWordWrap(true);layout->addWidget(l);};
    const QString target=plan.value("target").toString();
    label(tr("<b>Installation drive</b><br/>%1").arg(target.toHtmlEscaped()),"coreOfflineReviewCard");
    if(!error.isEmpty()) {label(error.toHtmlEscaped(),"coreOfflineEraseWarning");return widget;}
    const bool erase=plan.value("mode").toString()!=QStringLiteral("advanced");
    label(erase ? tr("<b>What will happen</b><br/>Erase every existing partition on this physical disk and create the layout below. Other physical disks are preserved.")
        : tr("<b>What will happen</b><br/>Format only the selected root partition. Reuse the selected EFI partition without formatting. Other existing partitions and physical disks are preserved."),"coreOfflineReviewCard");
    QString rows=QStringLiteral("<table cellpadding='5'><tr><th align='left'>Partition / size</th><th align='left'>Action</th><th align='left'>Mount</th></tr>");
    for(const auto& value:plan.value("disks").toArray()) {
        const auto disk=value.toObject();if(disk.value("path").toString()!=target) continue;
        for(const auto& entry:disk.value("partitions").toArray()) {
            const auto p=entry.toObject();QString action;
            if(p.value("mount").toString()==QStringLiteral("/")) action=tr("Format ext4; install Bitcoin Core Vault");
            else if(p.value("mount").toString()==QStringLiteral("/boot/efi")) action=p.value("new").toBool()?tr("Create EFI / FAT32"):tr("Reuse EFI; do not format");
            else if(p.value("new").toBool()) action=tr("Reserve unformatted: %1").arg(p.value("label").toString());
            else action=tr("Keep unchanged");
            QString name=p.value("path").toString();if(name.isEmpty()) name=tr("New partition");
            rows+=QStringLiteral("<tr><td>%1 — %2 GiB</td><td>%3</td><td>%4</td></tr>")
                .arg(name.toHtmlEscaped()).arg(p.value("size").toDouble()/(1024.0*1024*1024),0,'f',2)
                .arg(action.toHtmlEscaped(),p.value("mount").toString().toHtmlEscaped());
        }
    }
    rows+=QStringLiteral("</table>");label(rows,"coreOfflineReviewCard");
    label(erase?tr("All current files on %1 will be permanently erased.").arg(target.toHtmlEscaped()):tr("All current files on the selected root partition will be permanently erased. No existing partition is resized or moved."),"coreOfflineEraseWarning");
    layout->addStretch();return widget;
