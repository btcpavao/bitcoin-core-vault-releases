
// CORE_PARTITION_PLAN_V1: serialize the real mutable model and actual queued jobs.
QJsonObject
PartitionCoreModule::installPlan(const Config* config) const
{
    const QString target=m_bootLoaderInstallPath;
    const auto original=QJsonDocument::fromJson(coreOfflineDiskIdentity.value(target)).object();
    QString mode=config->installChoice()==Config::InstallChoice::Erase?QStringLiteral("erase"):QStringLiteral("advanced");
    if(mode==QStringLiteral("advanced") && QCoreApplication::instance()->property("coreInstallEraseDisk").toString()==target) mode=QStringLiteral("erase-layout");
    QJsonArray disks;
    for(const auto* info:m_deviceInfos) {
        auto* d=info->device.data(); QJsonArray parts,operations;
        if(d->partitionTable()) for(auto it=PartitionIterator::begin(d);it!=PartitionIterator::end(d);++it) {
            auto* p=*it; if(isPartitionFreeSpace(p)) continue;
            parts.append(QJsonObject{
                {"path",p->partitionPath()},{"first",double(p->firstSector()*d->logicalSize())},{"size",double(p->capacity())},
                {"fs",FileSystem::nameForType(p->fileSystem().type()).toLower()},{"label",p->label()},
                {"uuid",p->uuid()},{"mount",PartitionInfo::mountPoint(p)},
                {"format",PartitionInfo::format(p)},{"new",isPartitionNew(p)}});
        }
        for(const auto& job:info->jobs()) {
            QJsonObject operation{{"type",QString::fromLatin1(job->metaObject()->className())}};
            if(auto* pj=qobject_cast<PartitionJob*>(job.data())) {
                auto* p=pj->partition();
                operation.insert("first",double(p->firstSector()*d->logicalSize()));
                operation.insert("size",double(p->capacity()));operation.insert("path",p->partitionPath());
            }
            operations.append(operation);
        }
        const auto prior=QJsonDocument::fromJson(coreOfflineDiskIdentity.value(d->deviceNode())).object();
        disks.append(QJsonObject{{"path",d->deviceNode()},{"name",d->name()},
            {"logical_size",double(d->logicalSize())},{"table_before",prior.value("pttype").toString().isEmpty()?QStringLiteral("none"):prior.value("pttype").toString()},
            {"table_after",d->partitionTable() && d->partitionTable()->type()==PartitionTable::gpt?QStringLiteral("gpt"):QStringLiteral("other")},
            {"partitions",parts},{"jobs",operations}});
    }
    return QJsonObject{{"schema",1},{"product",QStringLiteral("CORE_PRODUCT_KEY")},{"mode",mode},
        {"firmware",PartUtils::isEfiSystem()?QStringLiteral("efi"):QStringLiteral("bios")},
        {"target",target},{"boot_target",m_bootLoaderInstallPath},{"expected",original},{"disks",disks}};
}
QString
PartitionCoreModule::validateInstallPlan(const Config* config) const
{
    return coreOfflineValidate(installPlan(config));
}
